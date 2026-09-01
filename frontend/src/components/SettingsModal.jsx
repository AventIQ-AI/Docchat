import React, { useState } from 'react';
import { X, Cpu, Download, CheckCircle2, Loader2, Sparkles, FileText } from 'lucide-react';

export const DEFAULT_MODELS = [
  { id: 'qwen2.5:1.5b', name: 'Qwen 2.5 1.5B', badge: 'Fast (1.1GB RAM)', tag: 'Recommended' },
  { id: 'qwen3:4b', name: 'Qwen 3 4B', badge: 'High Precision', tag: 'Accurate' },
  { id: 'llama3.2:1b', name: 'Llama 3.2 1B', badge: 'Meta 1B', tag: 'Compact' },
  { id: 'phi3:mini', name: 'Phi-3 Mini', badge: 'Microsoft 3.8B', tag: 'Reasoning' },
  { id: 'mistral:7b', name: 'Mistral 7B', badge: 'Mistral 7B', tag: 'Analytical' },
];

export default function SettingsModal({ 
  onClose, 
  installedModels = [], 
  onRefreshModels,
  onOpenModelManagement
}) {
  const [pullingModel, setPullingModel] = useState(null);
  const [activeTab, setActiveTab] = useState('models');

  const handlePullModel = async (modelId) => {
    setPullingModel(modelId);
    try {
      const res = await fetch('/api/models/pull', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelId }),
      });
      if (res.ok) {
        await onRefreshModels();
        alert(`Model '${modelId}' downloaded successfully!`);
      } else {
        alert(`Failed to download model '${modelId}'.`);
      }
    } catch (err) {
      alert(`Error pulling model: ${err.message}`);
    } finally {
      setPullingModel(null);
    }
  };

  const isInstalled = (modelId) => {
    return installedModels.some((m) => m.toLowerCase().includes(modelId.toLowerCase()));
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div 
        className="settings-modal" 
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', paddingBottom: '12px', borderBottom: '1px solid var(--border-subtle)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, fontSize: '1.1rem' }}>
            <Cpu size={18} style={{ color: 'var(--accent-teal)' }} />
            <span>Settings & Model Management</span>
          </div>
          <button className="icon-btn-ghost" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {/* Tab / Action Bar */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button 
              className={`badge-item ${activeTab === 'models' ? 'active' : ''}`}
              onClick={() => setActiveTab('models')}
              style={{ padding: '6px 12px', fontSize: '0.85rem' }}
            >
              <Sparkles size={14} />
              <span>Model Management</span>
            </button>
          </div>

          <a 
            href="/api/logs/csv" 
            download="app_activity.csv"
            className="theme-toggle-btn"
            style={{ padding: '5px 10px', fontSize: '0.75rem', textDecoration: 'none', gap: '4px' }}
            title="Download activity CSV logs"
          >
            <FileText size={13} style={{ color: 'var(--accent-teal)' }} />
            <span>Download CSV Logs</span>
          </a>
        </div>

        {/* Model List Table */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto', maxHeight: '380px' }}>
          {DEFAULT_MODELS.map((model) => {
            const downloaded = isInstalled(model.id);
            const isPulling = pullingModel === model.id;

            return (
              <div 
                key={model.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '12px 14px',
                  borderRadius: '12px',
                  backgroundColor: 'var(--bg-card)',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span>{model.name}</span>
                    <span className="model-tag-badge">{model.tag}</span>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                    Tag: <code>{model.id}</code> • {model.badge}
                  </div>
                </div>

                <div>
                  {downloaded ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#10b981', fontSize: '0.8rem', fontWeight: 600 }}>
                      <CheckCircle2 size={16} />
                      <span>Downloaded</span>
                    </div>
                  ) : (
                    <button 
                      className="theme-toggle-btn"
                      onClick={() => handlePullModel(model.id)}
                      disabled={isPulling}
                      style={{ padding: '5px 10px', fontSize: '0.75rem', gap: '4px' }}
                    >
                      {isPulling ? <Loader2 size={13} className="spin" /> : <Download size={13} />}
                      <span>{isPulling ? 'Downloading...' : 'Download'}</span>
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '16px', textAlign: 'center' }}>
          Models are stored locally in your Ollama library.
        </div>
      </div>
    </div>
  );
}
