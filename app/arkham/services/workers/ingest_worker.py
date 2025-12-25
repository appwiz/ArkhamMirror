"""
Ingest Worker - Entry point for document ingestion pipeline.

This worker handles:
1. Deduplication check via file hash
2. Moving files to permanent storage
3. Text passthrough for text-based files (skip OCR)
4. Converting non-PDF/non-text files to PDF
5. Creating document records
6. Enqueuing splitter jobs for processing (or direct embedding for text files)
"""

import os
import sys # Keep sys for shutil
import shutil
import logging
from datetime import datetime
from pathlib import Path

from rq import Queue
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import DATABASE_URL, REDIS_URL, DOCUMENTS_DIR

from app.arkham.services.db.models import Document, Chunk, MiniDoc, DateMention, TimelineEvent, SensitiveDataMatch, ExtractedTable
from app.arkham.services.utils.hash_utils import get_file_hash
from app.arkham.services.utils.security_utils import sanitize_filename
from app.arkham.services.converters import is_text_based_file, extract_text_direct, extract_tables_from_text
from app.arkham.services.timeline_service import extract_timeline_from_chunk
from app.arkham.services.utils.pattern_detector import detect_sensitive_data
from app.arkham.services.utils.smart_chunker import smart_chunk, agentic_chunk, ChunkConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup DB & Redis from central config
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
redis_conn = Redis.from_url(REDIS_URL)
q = Queue(connection=redis_conn)


def _process_text_directly(session, doc, extracted_data):
    """
    Process text-based files directly without OCR.
    Creates chunks and enqueues embedding jobs.

    Args:
        session: SQLAlchemy session
        doc: Document record
        extracted_data: Dict with 'text' and optional 'metadata' from extract_text_direct()

    Returns:
        Number of chunks created
    """
    text = extracted_data.get("text", "")
    metadata = extracted_data.get("metadata", {})

    if not text.strip():
        logger.warning(f"No text extracted from document {doc.id}")
        return 0

    # Store email metadata if present
    if metadata:
        # Update document with extracted metadata
        if metadata.get("email_subject"):
            doc.pdf_subject = metadata.get("email_subject")  # Reusing pdf_subject field
        if metadata.get("email_from"):
            doc.pdf_author = metadata.get("email_from")  # Reusing pdf_author field
        if metadata.get("email_date"):
            try:
                from email.utils import parsedate_to_datetime
                doc.pdf_creation_date = parsedate_to_datetime(metadata.get("email_date"))
            except Exception:
                pass
        # Store full metadata as JSON in a notes field or similar if available
        logger.info(f"Email metadata extracted: {list(metadata.keys())}")

    # Extract tables from text and create ExtractedTable records
    try:
        tables = extract_tables_from_text(text)
        for table_data in tables:
            ext_table = ExtractedTable(
                doc_id=doc.id,
                page_num=table_data["page_num"],
                table_index=table_data["table_index"],
                row_count=table_data["row_count"],
                col_count=table_data["col_count"],
                headers=table_data["headers"],
                text_content=table_data["text_content"],
            )
            session.add(ext_table)

        if tables:
            logger.info(f"Extracted {len(tables)} tables from text-based file (doc_id={doc.id})")
    except Exception as e:
        logger.warning(f"Table extraction from text failed (non-fatal): {e}")

    # Create a single MiniDoc for text files (they're typically small)
    minidoc_id = f"{doc.file_hash}__text_001"
    minidoc = MiniDoc(
        document_id=doc.id,
        minidoc_id=minidoc_id,
        page_start=1,
        page_end=1,
        status="parsed",  # Already have the text
    )
    session.add(minidoc)
    session.flush()

    # Determine chunking strategy from Redis
    chunking_strategy = "smart"  # Default
    try:
        strategy = redis_conn.get("arkham:chunking_strategy")
        if strategy:
            chunking_strategy = strategy.decode()
            logger.info(f"Using chunking strategy from Redis: {chunking_strategy}")
    except Exception as e:
        logger.debug(f"Could not read chunking strategy from Redis: {e}")

    # Chunk the text using smart/agentic chunking
    config = ChunkConfig(max_chunk_size=512, min_chunk_size=100, overlap=50)

    if chunking_strategy == "agentic":
        logger.info("Using agentic (LLM-based) chunking for text file")
        chunks_list = agentic_chunk(text, config)
    else:
        logger.info("Using smart recursive chunking for text file")
        chunks_list = smart_chunk(text, config)

    logger.info(f"Created {len(chunks_list)} chunks from {len(text)} characters")

    chunk_ids = []  # Collect chunk IDs for embedding after commit

    for chunk_index, chunk_text in enumerate(chunks_list):

        chunk = Chunk(
            doc_id=doc.id,
            text=chunk_text,
            chunk_index=chunk_index,
        )
        session.add(chunk)
        session.flush()  # Get ID
        chunk_ids.append(chunk.id)

        # Extract timeline information
        try:
            date_mentions, timeline_events = extract_timeline_from_chunk(
                chunk_text, chunk.id, doc.id
            )

            for mention_data in date_mentions:
                mention = DateMention(**mention_data)
                session.add(mention)

            for event_data in timeline_events:
                event = TimelineEvent(**event_data)
                session.add(event)

        except Exception as e:
            logger.warning(f"Timeline extraction failed for chunk {chunk.id}: {str(e)}")

        # Detect sensitive data patterns
        try:
            sensitive_matches = detect_sensitive_data(chunk_text)

            for match in sensitive_matches:
                sensitive_data = SensitiveDataMatch(
                    chunk_id=chunk.id,
                    doc_id=doc.id,
                    pattern_type=match.pattern_type,
                    match_text=match.match_text,
                    confidence=match.confidence,
                    start_pos=match.start_pos,
                    end_pos=match.end_pos,
                    context_before=match.context_before,
                    context_after=match.context_after
                )
                session.add(sensitive_data)

        except Exception as e:
            logger.warning(f"Sensitive data detection failed for chunk {chunk.id}: {str(e)}")

    doc.num_pages = 1  # Text files are treated as single-page
    doc.status = "embedded"  # Mark as ready (embedding jobs will be queued)

    # IMPORTANT: Commit all chunks to database BEFORE enqueueing embed jobs
    # This ensures workers can find the chunks when they start processing
    session.commit()
    logger.info(f"Text passthrough: {len(chunk_ids)} chunks committed to database")

    # Now enqueue embed jobs - chunks are guaranteed to exist in DB
    for chunk_id in chunk_ids:
        q.enqueue("app.arkham.services.workers.embed_worker.embed_chunk_job", chunk_id=chunk_id)

    logger.info(f"Text passthrough complete for doc {doc.id}: {len(chunk_ids)} embed jobs enqueued")
    return len(chunk_ids)


def process_file(file_path, project_id=None, ocr_mode="paddle"):
    """
    Process a single uploaded file through the ingestion pipeline.

    Args:
        file_path: Path to the uploaded file
        project_id: Optional project ID to associate with the document
        ocr_mode: OCR mode to use - "paddle" (fast) or "qwen" (smart)
    """
    logger.info("=" * 80)
    logger.info("INGEST_WORKER: process_file() called")
    logger.info(f"  file_path: {file_path}")
    logger.info(f"  project_id: {project_id}")
    logger.info(f"  ocr_mode: {ocr_mode}")
    logger.info(f"  File exists: {os.path.exists(file_path)}")
    logger.info("=" * 80)

    session = Session()
    try:
        logger.info(
            f"Processing: {file_path} (Project ID: {project_id}, Mode: {ocr_mode})"
        )

        # 1. Deduplication Check
        logger.info("Step 1: Computing file hash for deduplication...")
        file_hash = get_file_hash(file_path)
        logger.info(f"File hash: {file_hash}")

        existing = session.query(Document).filter_by(file_hash=file_hash).first()
        if existing:
            logger.warning(f"Duplicate file skipped: {os.path.basename(file_path)}")
            # Move to processed anyway so it doesn't get picked up again
            processed_dir = os.path.join(os.path.dirname(file_path), "processed")
            os.makedirs(processed_dir, exist_ok=True)
            shutil.move(
                file_path,
                os.path.join(processed_dir, os.path.basename(file_path)),
            )
            return

        # 2. Move to Permanent Storage (DataSilo/documents/)
        storage_dir = str(DOCUMENTS_DIR)
        os.makedirs(storage_dir, exist_ok=True)

        new_filename = f"{file_hash}_{sanitize_filename(os.path.basename(file_path))}"
        permanent_path = os.path.join(storage_dir, new_filename)

        shutil.move(file_path, permanent_path)
        logger.info(f"Moved file to {permanent_path}")

        # 2.5 Check if text-based file (can skip OCR)
        ext = os.path.splitext(permanent_path)[1].lower()

        if is_text_based_file(permanent_path):
            # TEXT PASSTHROUGH: Extract text directly, skip OCR pipeline
            logger.info(f"Text-based file detected ({ext}), using text passthrough...")

            extracted_data = extract_text_direct(permanent_path)
            if extracted_data and extracted_data.get("text"):
                # Create Document Record
                doc = Document(
                    title=os.path.basename(file_path),
                    path=permanent_path,
                    source_path=os.path.dirname(file_path),
                    file_hash=file_hash,
                    doc_type=ext,
                    project_id=project_id,
                    status="processing",
                    num_pages=1,
                )
                session.add(doc)
                session.commit()

                # Process text directly (chunks + embed jobs)
                # Note: _process_text_directly commits internally before enqueueing embed jobs
                chunk_count = _process_text_directly(session, doc, extracted_data)

                logger.info(f"Text passthrough complete: {chunk_count} chunks from {ext} file")
                return
            else:
                logger.warning(f"Text extraction failed for {ext}, falling back to PDF conversion...")

        # 2.6 Conversion to PDF (for non-text files or failed text extraction)
        final_processing_path = permanent_path

        if ext != ".pdf":
            try:
                from app.arkham.services.converters import convert_to_pdf

                logger.info(f"Converting {ext} to PDF...")
                converted_pdf_path = convert_to_pdf(permanent_path)
                final_processing_path = converted_pdf_path
                logger.info(f"Conversion successful: {final_processing_path}")
            except Exception as conv_err:
                logger.error(f"Conversion failed: {conv_err}")
                raise conv_err

        # 3. Create Document Record
        doc = Document(
            title=os.path.basename(file_path),
            path=permanent_path,
            source_path=os.path.dirname(file_path),
            file_hash=file_hash,
            doc_type=ext,
            project_id=project_id,
            status="uploaded",
            num_pages=0,
        )
        session.add(doc)
        session.commit()

        # 4. Enqueue Splitter Job (for PDF/OCR pipeline)
        q.enqueue(
            "app.arkham.services.workers.splitter_worker.split_pdf_job",
            doc_id=doc.id,
            file_path=final_processing_path,
            ocr_mode=ocr_mode,
        )

        logger.info(f"Enqueued split job for {final_processing_path}")

    except Exception as e:
        session.rollback()
        logger.error(f"FAILED {file_path}: {e}")
        # Dead Letter Queue
        failed_dir = os.path.join(os.path.dirname(file_path), "failed")
        os.makedirs(failed_dir, exist_ok=True)
        shutil.move(file_path, os.path.join(failed_dir, os.path.basename(file_path)))
        with open(os.path.join(failed_dir, "errors.log"), "a") as log:
            log.write(f"{datetime.now()} - {file_path} - {e}\n")
    finally:
        session.close()
