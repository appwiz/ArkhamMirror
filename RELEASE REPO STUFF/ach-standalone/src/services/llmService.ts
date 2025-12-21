import { LLMConfig, Analysis, Hypothesis, Evidence } from '../types';

interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

interface CompletionResponse {
  success: boolean;
  content: string;
  error?: string;
}

// System prompts for different ACH tasks
const SYSTEM_PROMPTS = {
  hypotheses: `You are an expert analyst helping with Analysis of Competing Hypotheses (ACH).
Your task is to suggest alternative hypotheses for the given focus question.
Generate 3-5 distinct, mutually exclusive hypotheses that could explain the situation.
Each hypothesis should be concise (1-2 sentences) and testable.
Format your response as a numbered list, one hypothesis per line.
Do not include explanations - just the hypotheses themselves.`,

  evidence: `You are an expert analyst helping with Analysis of Competing Hypotheses (ACH).
Your task is to suggest relevant evidence items that could help distinguish between the hypotheses.
Consider facts, documents, testimony, assumptions, and logical arguments.
Generate 3-5 evidence items that would be diagnostic (help distinguish between hypotheses).
Format your response as a numbered list with brief descriptions.
Include the type (fact/testimony/document/assumption/argument) in parentheses.`,

  ratingHelp: `You are an expert analyst helping with Analysis of Competing Hypotheses (ACH).
Your task is to explain how consistent a piece of evidence is with a hypothesis.
Use this rating scale:
- CC (Very Consistent): Strong support for the hypothesis
- C (Consistent): Supports the hypothesis
- N (Neutral): Neither supports nor contradicts
- I (Inconsistent): Contradicts the hypothesis
- II (Very Inconsistent): Strongly contradicts the hypothesis
Provide a brief explanation (2-3 sentences) for your suggested rating.`,

  analysisInsights: `You are an expert analyst helping with Analysis of Competing Hypotheses (ACH).
Analyze the current state of the ACH matrix and provide insights.
Consider:
- Which hypothesis has the strongest support and why
- Key evidence that distinguishes between hypotheses
- Potential gaps in the evidence
- Cognitive biases to watch for
- Recommendations for further investigation
Be concise but thorough.`,

  milestones: `You are an expert analyst helping with Analysis of Competing Hypotheses (ACH).
Your task is to suggest future milestones or indicators that would help confirm or refute the hypotheses.
These are observable events or data points that, if they occur, would significantly change the analysis.
Generate 2-3 specific, observable milestones for each relevant hypothesis.
Format: "[Hypothesis Label]: [Milestone description]"`,

  ratings: `You are an expert analyst helping with Analysis of Competing Hypotheses (ACH).
Your task is to suggest ratings for how consistent a piece of evidence is with each hypothesis.
Use this rating scale:
- CC (Very Consistent): The evidence strongly supports this hypothesis
- C (Consistent): The evidence somewhat supports this hypothesis
- N (Neutral): The evidence neither supports nor contradicts this hypothesis
- I (Inconsistent): The evidence somewhat contradicts this hypothesis
- II (Very Inconsistent): The evidence strongly contradicts this hypothesis

For each hypothesis, provide a rating and a brief explanation (1 sentence).
Format each line as: "[Hypothesis Label]: [RATING] - [Brief explanation]"
Example: "H1: CC - This evidence directly supports the hypothesis because..."`,

  devilsAdvocate: `You are a devil's advocate challenging an intelligence analysis.
Your role is to stress-test hypotheses by finding weaknesses, counter-arguments, and blind spots.
Be critical but constructive - the goal is to strengthen the analysis by identifying what could be wrong.
For each hypothesis, provide:
1. The strongest counter-argument against this hypothesis
2. What evidence would DISPROVE this hypothesis (if found)
3. An alternative angle or consideration they may have missed`,
};

export async function callLLM(
  config: LLMConfig,
  messages: ChatMessage[]
): Promise<CompletionResponse> {
  if (!config.enabled) {
    return { success: false, content: '', error: 'LLM is not enabled' };
  }

  try {
    const isAnthropic = config.provider === 'anthropic';

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    if (config.apiKey) {
      if (isAnthropic) {
        headers['x-api-key'] = config.apiKey;
        headers['anthropic-version'] = '2023-06-01';
      } else {
        headers['Authorization'] = `Bearer ${config.apiKey}`;
      }
    }

    let response: Response;

    if (isAnthropic) {
      // Anthropic uses a different API format
      const systemMessage = messages.find(m => m.role === 'system')?.content || '';
      const otherMessages = messages.filter(m => m.role !== 'system');

      response = await fetch(`${config.endpoint}/messages`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          model: config.model,
          max_tokens: 4096,
          system: systemMessage,
          messages: otherMessages.map(m => ({
            role: m.role,
            content: m.content,
          })),
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        return { success: false, content: '', error: `HTTP ${response.status}: ${errorText}` };
      }

      const data = await response.json();
      return { success: true, content: data.content[0]?.text || '' };
    } else {
      // OpenAI-compatible API (LM Studio, Ollama, OpenAI, Groq)
      response = await fetch(`${config.endpoint}/chat/completions`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          model: config.model,
          messages,
          max_tokens: 4096,
          temperature: 0.7,
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        return { success: false, content: '', error: `HTTP ${response.status}: ${errorText}` };
      }

      const data = await response.json();
      return { success: true, content: data.choices[0]?.message?.content || '' };
    }
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    const isCorsError = errorMessage.includes('Failed to fetch') ||
                        errorMessage.includes('NetworkError');

    return {
      success: false,
      content: '',
      error: isCorsError
        ? 'CORS error - Enable CORS in your local LLM server'
        : errorMessage
    };
  }
}

// Helper functions for specific ACH tasks

export async function suggestHypotheses(
  config: LLMConfig,
  focusQuestion: string,
  existingHypotheses: Hypothesis[]
): Promise<CompletionResponse> {
  const existingList = existingHypotheses.length > 0
    ? `\n\nExisting hypotheses to avoid duplicating:\n${existingHypotheses.map(h => `- ${h.description}`).join('\n')}`
    : '';

  return callLLM(config, [
    { role: 'system', content: SYSTEM_PROMPTS.hypotheses },
    { role: 'user', content: `Focus Question: ${focusQuestion}${existingList}\n\nSuggest alternative hypotheses:` },
  ]);
}

export async function suggestEvidence(
  config: LLMConfig,
  focusQuestion: string,
  hypotheses: Hypothesis[],
  existingEvidence: Evidence[]
): Promise<CompletionResponse> {
  const hypothesesList = hypotheses.map(h => `- ${h.label}: ${h.description}`).join('\n');
  const existingList = existingEvidence.length > 0
    ? `\n\nExisting evidence to avoid duplicating:\n${existingEvidence.map(e => `- ${e.description}`).join('\n')}`
    : '';

  return callLLM(config, [
    { role: 'system', content: SYSTEM_PROMPTS.evidence },
    { role: 'user', content: `Focus Question: ${focusQuestion}\n\nHypotheses:\n${hypothesesList}${existingList}\n\nSuggest diagnostic evidence items:` },
  ]);
}

export async function getRatingHelp(
  config: LLMConfig,
  evidence: Evidence,
  hypothesis: Hypothesis,
  focusQuestion: string
): Promise<CompletionResponse> {
  return callLLM(config, [
    { role: 'system', content: SYSTEM_PROMPTS.ratingHelp },
    { role: 'user', content: `Focus Question: ${focusQuestion}\n\nHypothesis (${hypothesis.label}): ${hypothesis.description}\n\nEvidence: ${evidence.description}\nType: ${evidence.evidenceType}\nReliability: ${evidence.reliability}\n\nHow consistent is this evidence with this hypothesis? Suggest a rating and explain:` },
  ]);
}

export async function getAnalysisInsights(
  config: LLMConfig,
  analysis: Analysis
): Promise<CompletionResponse> {
  // Build a summary of the current analysis state
  const hypothesesSummary = analysis.hypotheses.map(h => `- ${h.label}: ${h.description}`).join('\n');
  const evidenceSummary = analysis.evidence.map(e => `- ${e.label}: ${e.description} (${e.evidenceType}, ${e.reliability} reliability)`).join('\n');

  // Build matrix summary
  const matrixRows: string[] = [];
  for (const e of analysis.evidence) {
    const ratings = analysis.hypotheses.map(h => {
      const rating = analysis.ratings.find(r => r.evidenceId === e.id && r.hypothesisId === h.id);
      return `${h.label}:${rating?.rating || '-'}`;
    }).join(', ');
    matrixRows.push(`${e.label}: ${ratings}`);
  }
  const matrixSummary = matrixRows.join('\n');

  return callLLM(config, [
    { role: 'system', content: SYSTEM_PROMPTS.analysisInsights },
    { role: 'user', content: `Focus Question: ${analysis.focusQuestion}\n\nHypotheses:\n${hypothesesSummary}\n\nEvidence:\n${evidenceSummary}\n\nMatrix (Evidence: Hypothesis:Rating):\n${matrixSummary}\n\nProvide analysis insights:` },
  ]);
}

export async function suggestMilestones(
  config: LLMConfig,
  analysis: Analysis
): Promise<CompletionResponse> {
  const hypothesesSummary = analysis.hypotheses.map(h => `- ${h.label}: ${h.description}`).join('\n');
  const existingMilestones = analysis.milestones.length > 0
    ? `\n\nExisting milestones:\n${analysis.milestones.map(m => {
        const h = analysis.hypotheses.find(h => h.id === m.hypothesisId);
        return `- ${h?.label || '?'}: ${m.description}`;
      }).join('\n')}`
    : '';

  return callLLM(config, [
    { role: 'system', content: SYSTEM_PROMPTS.milestones },
    { role: 'user', content: `Focus Question: ${analysis.focusQuestion}\n\nHypotheses:\n${hypothesesSummary}${existingMilestones}\n\nSuggest future milestones or indicators to watch for:` },
  ]);
}

export interface RatingSuggestion {
  hypothesisId: string;
  hypothesisLabel: string;
  rating: string;
  explanation: string;
}

export async function suggestRatings(
  config: LLMConfig,
  focusQuestion: string,
  evidence: Evidence,
  hypotheses: Hypothesis[]
): Promise<{ success: boolean; suggestions: RatingSuggestion[]; error?: string }> {
  const hypothesesList = hypotheses.map(h => `- ${h.label}: ${h.description}`).join('\n');

  const result = await callLLM(config, [
    { role: 'system', content: SYSTEM_PROMPTS.ratings },
    {
      role: 'user',
      content: `Focus Question: ${focusQuestion}

Evidence to rate:
- Description: ${evidence.description}
- Type: ${evidence.evidenceType}
- Reliability: ${evidence.reliability}
${evidence.source ? `- Source: ${evidence.source}` : ''}

Hypotheses:
${hypothesesList}

For this evidence, suggest a rating (CC/C/N/I/II) for each hypothesis and explain your reasoning:`,
    },
  ]);

  if (!result.success) {
    return { success: false, suggestions: [], error: result.error };
  }

  // Parse the response - format is "H1: CC - explanation"
  const suggestions: RatingSuggestion[] = [];
  const lines = result.content.split('\n').filter(line => line.trim().length > 0);

  for (const line of lines) {
    // Match patterns like "H1: CC - explanation" or "[H1] CC: explanation"
    const match = line.match(/\[?(H\d+)\]?:?\s*(CC|C|N|I|II)\s*[-:]\s*(.+)/i);
    if (match) {
      const hLabel = match[1].toUpperCase();
      const hypothesis = hypotheses.find(h => h.label === hLabel);
      if (hypothesis) {
        suggestions.push({
          hypothesisId: hypothesis.id,
          hypothesisLabel: hLabel,
          rating: match[2].toUpperCase(),
          explanation: match[3].trim(),
        });
      }
    }
  }

  return { success: true, suggestions };
}

export interface Challenge {
  hypothesisId: string;
  hypothesisLabel: string;
  counterArgument: string;
  disproofEvidence: string;
  alternativeAngle: string;
}

export async function challengeHypotheses(
  config: LLMConfig,
  focusQuestion: string,
  hypotheses: Hypothesis[],
  targetHypothesisId?: string // If provided, only challenge this hypothesis
): Promise<{ success: boolean; challenges: Challenge[]; error?: string }> {
  // Filter to target hypothesis if specified
  const hypothesesToChallenge = targetHypothesisId
    ? hypotheses.filter(h => h.id === targetHypothesisId)
    : hypotheses;

  if (hypothesesToChallenge.length === 0) {
    return { success: false, challenges: [], error: 'No hypotheses to challenge' };
  }

  const hypothesesList = hypothesesToChallenge.map(h => `${h.label}: ${h.description}`).join('\n');

  const result = await callLLM(config, [
    { role: 'system', content: SYSTEM_PROMPTS.devilsAdvocate },
    {
      role: 'user',
      content: `FOCUS QUESTION:
${focusQuestion}

HYPOTHESES TO CHALLENGE:
${hypothesesList}

Generate a challenge for EACH hypothesis. For each one, provide:
1. Counter-argument: The strongest argument AGAINST this hypothesis
2. Disproof evidence: What evidence would DISPROVE this hypothesis if found
3. Alternative angle: A consideration or angle they may have missed

Format your response as JSON:
{
  "challenges": [
    {
      "hypothesis_label": "H1",
      "counter_argument": "The main weakness...",
      "disproof_evidence": "This would be disproved if...",
      "alternative_angle": "Consider instead..."
    }
  ]
}`,
    },
  ]);

  if (!result.success) {
    return { success: false, challenges: [], error: result.error };
  }

  console.log('Raw LLM response for challenges:', result.content);

  try {
    // Clean up the response - remove markdown code blocks if present
    let cleaned = result.content;
    if (cleaned.includes('```json')) {
      cleaned = cleaned.split('```json')[1].split('```')[0];
    } else if (cleaned.includes('```')) {
      const parts = cleaned.split('```');
      if (parts.length > 1) {
        cleaned = parts[1];
      }
    }

    const data = JSON.parse(cleaned);
    const rawChallenges = data.challenges || [];
    console.log('Parsed challenges from LLM:', rawChallenges);
    console.log('Available hypotheses:', hypotheses.map(h => h.label));

    // Map to our Challenge interface
    const challenges: Challenge[] = rawChallenges
      .map((c: { hypothesis_label?: string; counter_argument?: string; disproof_evidence?: string; alternative_angle?: string }) => {
        const hypothesis = hypotheses.find(h => h.label === c.hypothesis_label);
        if (!hypothesis) return null;
        return {
          hypothesisId: hypothesis.id,
          hypothesisLabel: c.hypothesis_label || '',
          counterArgument: c.counter_argument || '',
          disproofEvidence: c.disproof_evidence || '',
          alternativeAngle: c.alternative_angle || '',
        };
      })
      .filter((c: Challenge | null): c is Challenge => c !== null);

    return { success: true, challenges };
  } catch {
    // If JSON parsing fails, try to extract challenges from text
    return { success: false, challenges: [], error: 'Failed to parse AI response as JSON' };
  }
}
