import { ReactNode, useEffect } from 'react';
import { X } from 'lucide-react';

interface DialogProps {
  open?: boolean;
  isOpen?: boolean; // alias for open
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl' | '2xl';
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl'; // alias for size
}

export function Dialog({ open, isOpen, onClose, title, children, size = 'md', maxWidth }: DialogProps) {
  // Support both open and isOpen props
  const isDialogOpen = open ?? isOpen ?? false;
  // Support both size and maxWidth props
  const dialogSize = maxWidth ?? size;

  // Handle escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isDialogOpen) {
        onClose();
      }
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isDialogOpen, onClose]);

  // Prevent body scroll when open
  useEffect(() => {
    if (isDialogOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [isDialogOpen]);

  if (!isDialogOpen) return null;

  const sizes = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
    '2xl': 'max-w-2xl',
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70"
        onClick={onClose}
      />

      {/* Dialog */}
      <div className={`relative w-full ${sizes[dialogSize]} bg-gray-800 rounded-xl shadow-2xl border border-gray-700`}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold text-white">{title}</h2>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-white hover:bg-gray-700 rounded transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-4">
          {children}
        </div>
      </div>
    </div>
  );
}
