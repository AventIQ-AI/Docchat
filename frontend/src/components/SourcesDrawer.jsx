import React from 'react';
import { X, FileText, Target, MapPin } from 'lucide-react';

export default function SourcesDrawer({ source, tagNumber, onClose }) {
  if (!source) return null;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="drawer">
        <div className="drawer-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span className="citation-pill" style={{ fontSize: '0.85rem', padding: '4px 10px' }}>
              [S{tagNumber}]
            </span>
            <span style={{ fontWeight: 600, fontSize: '1.05rem' }}>Retrieved Source</span>
          </div>
          <button className="doc-delete" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="source-card">
          <div className="source-meta">
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <FileText size={14} style={{ color: 'var(--accent-primary)' }} />
              <strong style={{ color: 'var(--text-main)' }}>{source.file_name}</strong>
            </div>
            {source.page_number && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                <MapPin size={12} />
                <span>Page {source.page_number}</span>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', color: '#34d399', margin: '8px 0 12px' }}>
            <Target size={14} />
            <span>Cosine Similarity: {(source.similarity * 100).toFixed(1)}%</span>
          </div>

          <div className="source-text">
            {source.text}
          </div>
        </div>

        <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: 'auto' }}>
          Path: {source.source_path}
        </div>
      </div>
    </>
  );
}
