import React, { useMemo } from 'react';
import { Bot, User, FileText, Bookmark, ExternalLink } from 'lucide-react';
import ReactMarkdown from 'react-markdown';

export default function ChatMessage({ message, onSelectSource }) {
  const isUser = message.role === 'user';
  const sources = message.sources || [];

  // Deduplicate sources by file_name so exact same document references are not repeated
  const uniqueSources = useMemo(() => {
    const list = [];
    const seen = new Set();

    sources.forEach((src, idx) => {
      const fileKey = src.file_name || src.source_path;
      if (!seen.has(fileKey)) {
        seen.add(fileKey);
        list.push({
          ...src,
          tagNumber: idx + 1,
        });
      }
    });

    return list;
  }, [sources]);

  const renderMessageContent = (text) => {
    if (!text) return null;

    // Split on inline citation tags like [S1], [S2], [S15]
    const parts = text.split(/(\[S\d+\])/g);

    return parts.map((part, idx) => {
      const match = part.match(/^\[S(\d+)\]$/);
      if (match) {
        const sourceIndex = parseInt(match[1], 10) - 1;
        const sourceData = sources[sourceIndex];

        return (
          <span
            key={idx}
            className="citation-pill"
            onClick={() => sourceData && onSelectSource(sourceData, sourceIndex + 1)}
            title={
              sourceData
                ? `${sourceData.file_name} ${sourceData.page_number ? `(Page ${sourceData.page_number})` : ''} • Match: ${(sourceData.similarity * 100).toFixed(1)}%`
                : `Citation [S${match[1]}]`
            }
          >
            <FileText size={11} />
            S{match[1]}
          </span>
        );
      }

      return <ReactMarkdown key={idx} components={{ p: 'span' }}>{part}</ReactMarkdown>;
    });
  };

  return (
    <div className={`message-wrapper ${isUser ? 'user' : 'assistant'}`}>
      <div className={`avatar-round ${isUser ? 'user' : 'assistant'}`}>
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </div>

      <div className="message-body">
        {isUser ? (
          <div>
            {message.attachments && message.attachments.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '6px' }}>
                {message.attachments.map((fileName, idx) => (
                  <div key={idx} className="file-chip">
                    <FileText size={12} />
                    <span>{fileName}</span>
                  </div>
                ))}
              </div>
            )}
            <div>{message.content}</div>
          </div>
        ) : (
          <div>
            {/* Assistant Markdown Content with Inline Citation Badges */}
            <div className="assistant-text-content">
              {renderMessageContent(message.content)}
            </div>

            {/* Deduplicated Citations Footer Box */}
            {uniqueSources.length > 0 && (
              <div className="citations-footer-box">
                <div className="citations-header">
                  <Bookmark size={13} style={{ color: 'var(--accent-teal)' }} />
                  <span>Retrieved Document Citation{uniqueSources.length > 1 ? 's' : ''} ({uniqueSources.length})</span>
                </div>

                <div className="citations-chips-grid">
                  {uniqueSources.map((src, i) => (
                    <div
                      key={i}
                      className="source-chip-badge"
                      onClick={() => onSelectSource(src, src.tagNumber)}
                      title={`Click to view snippet from ${src.file_name}`}
                    >
                      <span className="source-tag-name">S{src.tagNumber}</span>
                      <span className="source-file-title">{src.file_name}</span>
                      <span className="source-match-score">{(src.similarity * 100).toFixed(0)}%</span>
                      <ExternalLink size={10} style={{ opacity: 0.6 }} />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
