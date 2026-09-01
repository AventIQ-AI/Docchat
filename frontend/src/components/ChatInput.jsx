import React, { useRef, useEffect } from 'react';
import { Plus, ArrowUp, X, FileText, Sliders } from 'lucide-react';

export default function ChatInput({ 
  input, 
  setInput, 
  attachedFiles,
  setAttachedFiles,
  onSend, 
  isLoading, 
  topK, 
  setTopK
}) {
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);

  // Auto-expand textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
    }
  }, [input]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if ((input.trim() || attachedFiles.length > 0) && !isLoading) {
        onSend();
      }
    }
  };

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      const newFiles = Array.from(e.target.files);
      setAttachedFiles((prev) => [...prev, ...newFiles]);
      e.target.value = '';
    }
  };

  const removeAttachedFile = (indexToRemove) => {
    setAttachedFiles((prev) => prev.filter((_, idx) => idx !== indexToRemove));
  };

  return (
    <div className="input-container-floating">
      <div className="capsule-card">
        {/* File Attachment Previews */}
        {attachedFiles.length > 0 && (
          <div className="attachment-previews">
            {attachedFiles.map((file, idx) => (
              <div key={idx} className="file-chip">
                <FileText size={12} style={{ color: 'var(--accent-teal)' }} />
                <span>{file.name}</span>
                <button 
                  className="file-chip-remove" 
                  onClick={() => removeAttachedFile(idx)}
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Text Area */}
        <textarea
          ref={textareaRef}
          className="chat-textarea"
          placeholder="Type a message..."
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
        />

        {/* Capsule Bottom Control Bar (Clean Layout) */}
        <div className="capsule-bottom-bar">
          {/* Left: Round '+' attachment button */}
          <input 
            type="file" 
            ref={fileInputRef} 
            style={{ display: 'none' }} 
            multiple 
            accept=".pdf,.docx,.txt,.md"
            onChange={handleFileSelect}
          />
          <button 
            className="plus-btn-circle" 
            onClick={() => fileInputRef.current?.click()} 
            title="Upload files or attach documents"
          >
            <Plus size={18} />
          </button>

          {/* Center: Top-K Selector Pill */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <div 
              className="badge-item"
              onClick={() => {
                const newK = prompt("Enter Top-K document chunks to retrieve (1-15):", topK);
                if (newK && !isNaN(newK)) setTopK(Math.max(1, Math.min(15, parseInt(newK, 10))));
              }}
              title="Click to adjust Top-K retrieval count"
              style={{ cursor: 'pointer' }}
            >
              <Sliders size={12} style={{ opacity: 0.7 }} />
              <span>Top-K: {topK}</span>
            </div>
          </div>

          {/* Right: Dark round '↑' Send button */}
          <button 
            className="send-btn-circle" 
            onClick={onSend} 
            disabled={(!input.trim() && attachedFiles.length === 0) || isLoading}
            title="Send message"
          >
            <ArrowUp size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
