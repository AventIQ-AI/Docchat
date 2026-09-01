import React from 'react';
import { 
  Zap, Edit3, Search, Settings, Trash2, 
  Sun, Moon, SidebarClose, SidebarOpen, CheckCircle2 
} from 'lucide-react';

export default function Sidebar({ 
  sessions,
  activeSessionId,
  onSelectSession,
  onDeleteSession,
  health, 
  onNewChat, 
  theme,
  onToggleTheme,
  onOpenSearch,
  onOpenSettings,
  isCollapsed,
  onToggleCollapse
}) {
  const isHealthy = health?.status === 'healthy';

  return (
    <div className={`sidebar ${isCollapsed ? 'collapsed' : ''}`}>
      {/* Sidebar Header: ⚡ Lightning Logo & Sidebar Collapse/Expand Toggle icon */}
      <div className="sidebar-header">
        {!isCollapsed && (
          <div className="brand-icon-box">
            <Zap size={16} />
          </div>
        )}
        <button 
          className="icon-btn-ghost" 
          onClick={onToggleCollapse}
          title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {isCollapsed ? <SidebarOpen size={18} /> : <SidebarClose size={18} />}
        </button>
      </div>

      {/* Main Menu Actions */}
      <div className="sidebar-menu">
        <div className="sidebar-menu-item" onClick={onNewChat} title="New chat">
          <Edit3 size={16} />
          <span>New chat</span>
        </div>
        <div className="sidebar-menu-item" onClick={onOpenSearch} title="Search">
          <Search size={16} />
          <span>Search</span>
        </div>
        <div className="sidebar-menu-item" onClick={onOpenSettings} title="Settings & Models">
          <Settings size={16} />
          <span>Settings</span>
        </div>
      </div>

      {/* Recent Conversations Section */}
      {!isCollapsed && (
        <div className="sidebar-section-label">
          Recent conversations
        </div>
      )}

      {!isCollapsed && (
        <div className="recent-conversations-list">
          {sessions.map((session) => (
            <div 
              key={session.id} 
              className={`conversation-item ${session.id === activeSessionId ? 'active' : ''}`}
              onClick={() => onSelectSession(session.id)}
            >
              <span className="conversation-title" title={session.title}>
                {session.title || 'New chat'}
              </span>
              <button 
                className="conversation-delete"
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteSession(session.id);
                }}
                title="Delete conversation"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}

          {sessions.length === 0 && (
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', padding: '8px 10px' }}>
              No recent conversations.
            </div>
          )}
        </div>
      )}

      {/* Sidebar Footer */}
      <div className="sidebar-footer">
        <button className="icon-btn-ghost" onClick={onToggleTheme} title="Toggle Dark/Light Mode">
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>

        {!isCollapsed && (
          <div className="sidebar-footer-info" style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            <CheckCircle2 size={13} style={{ color: isHealthy ? '#10b981' : '#ef4444' }} />
            <span>{health?.chat_model || 'qwen2.5:1.5b'}</span>
          </div>
        )}
      </div>
    </div>
  );
}
