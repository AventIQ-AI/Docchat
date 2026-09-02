import React, { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatMessage from './components/ChatMessage';
import ChatInput from './components/ChatInput';
import SourcesDrawer from './components/SourcesDrawer';
import SettingsModal from './components/SettingsModal';
import { Sparkles, ChevronDown, Check, Download, CheckCircle2 } from 'lucide-react';
import { DEFAULT_MODELS } from './components/SettingsModal';

const LOCAL_STORAGE_SESSIONS_KEY = 'rag_chat_sessions_v2';
const LOCAL_STORAGE_THEME_KEY = 'rag_theme_preference';

export default function App() {
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem(LOCAL_STORAGE_THEME_KEY) || 'light';
  });

  const [sessions, setSessions] = useState(() => {
    try {
      const saved = localStorage.getItem(LOCAL_STORAGE_SESSIONS_KEY);
      if (saved) return JSON.parse(saved);
    } catch (e) {
      console.error('Failed to load sessions from localStorage', e);
    }
    return [{ id: 'default-session', title: 'New chat', messages: [], docIds: [], createdAt: Date.now() }];
  });

  const [activeSessionId, setActiveSessionId] = useState(() => {
    return sessions[0]?.id || 'default-session';
  });

  const [input, setInput] = useState('');
  const [attachedFiles, setAttachedFiles] = useState([]);
  const [allDocuments, setAllDocuments] = useState([]);
  const [installedModels, setInstalledModels] = useState([]);
  const [health, setHealth] = useState(null);
  const [topK, setTopK] = useState(5);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [selectedModel, setSelectedModel] = useState('qwen2.5:1.5b');
  const [showTopRightModelDropdown, setShowTopRightModelDropdown] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [selectedSource, setSelectedSource] = useState(null);
  const [sourceTagNumber, setSourceTagNumber] = useState(null);

  const messagesEndRef = useRef(null);

  const activeSession = sessions.find((s) => s.id === activeSessionId) || sessions[0];
  const messages = activeSession ? activeSession.messages : [];
  const activeDocIds = activeSession ? (activeSession.docIds || []) : [];

  const sessionDocuments = allDocuments.filter((doc) => activeDocIds.includes(doc.id));

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(LOCAL_STORAGE_THEME_KEY, theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
  };

  useEffect(() => {
    try {
      localStorage.setItem(LOCAL_STORAGE_SESSIONS_KEY, JSON.stringify(sessions));
    } catch (e) {
      console.error('Failed to save sessions to localStorage', e);
    }
  }, [sessions]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  const fetchDocuments = async () => {
    try {
      const res = await fetch('/api/documents');
      if (res.ok) {
        const data = await res.json();
        setAllDocuments(data);
        return data;
      }
    } catch (err) {
      console.error('Failed to fetch documents:', err);
    }
    return [];
  };

  const fetchInstalledModels = async () => {
    try {
      const res = await fetch('/api/models');
      if (res.ok) {
        const data = await res.json();
        setInstalledModels(data.models || []);
        return data.models;
      }
    } catch (err) {
      console.error('Failed to fetch installed models:', err);
    }
    return [];
  };

  const fetchHealth = async () => {
    try {
      const res = await fetch('/api/health');
      if (res.ok) {
        const data = await res.json();
        setHealth(data);
      }
    } catch (err) {
      console.error('Failed to fetch health status:', err);
    }
  };

  useEffect(() => {
    fetchDocuments();
    fetchInstalledModels();
    fetchHealth();
    const interval = setInterval(fetchHealth, 15000);
    return () => clearInterval(interval);
  }, []);

  const isModelDownloaded = (modelId) => {
    return installedModels.some((m) => m.toLowerCase().includes(modelId.toLowerCase()));
  };

  const updateActiveSession = (newMessages, newDocIds = null, newTitle = null) => {
    setSessions((prevSessions) =>
      prevSessions.map((session) => {
        if (session.id === activeSessionId) {
          const updatedTitle =
            newTitle ||
            (session.messages.length === 0 && newMessages.length > 0 && newMessages[0].role === 'user'
              ? newMessages[0].content.slice(0, 32) || 'New chat'
              : session.title);

          const updatedDocIds = newDocIds !== null ? newDocIds : (session.docIds || []);

          return {
            ...session,
            title: updatedTitle,
            messages: newMessages,
            docIds: updatedDocIds,
          };
        }
        return session;
      })
    );
  };

  const handleNewChat = () => {
    const newSession = {
      id: `chat-${Date.now()}`,
      title: 'New chat',
      messages: [],
      docIds: [],
      createdAt: Date.now(),
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(newSession.id);
    setInput('');
    setAttachedFiles([]);
  };

  const handleSelectSession = (id) => {
    setActiveSessionId(id);
    setInput('');
    setAttachedFiles([]);
  };

  const handleDeleteSession = (id) => {
    const remaining = sessions.filter((s) => s.id !== id);
    if (remaining.length === 0) {
      const fresh = [{ id: `chat-${Date.now()}`, title: 'New chat', messages: [], docIds: [], createdAt: Date.now() }];
      setSessions(fresh);
      setActiveSessionId(fresh[0].id);
    } else {
      setSessions(remaining);
      if (activeSessionId === id) {
        setActiveSessionId(remaining[0].id);
      }
    }
  };

  const uploadAndIndexFiles = async (files) => {
    if (!files || files.length === 0) return [];
    setIsUploading(true);

    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));

    try {
      const res = await fetch('/api/documents/upload', {
        method: 'POST',
        body: formData,
      });

      if (res.ok) {
        const uploadData = await res.json();
        const freshDocs = await fetchDocuments();
        await fetchHealth();

        // Normalize paths for cross-platform compatibility
        const uploadedNames = uploadData.results.map((r) => r.file_name);
        const uploadedPaths = uploadData.results.map((r) => (r.source_path || '').replace(/\\/g, '/'));

        const failedItems = uploadData.results.filter((r) => r.status === 'FAILED');
        if (failedItems.length > 0) {
          alert(`Upload warning: ${failedItems.map((f) => f.file_name + ': ' + (f.error || 'parsing failed')).join(', ')}`);
        }

        const newDocIds = freshDocs
          .filter((d) => 
            uploadedPaths.includes((d.source_path || '').replace(/\\/g, '/')) || 
            uploadedNames.includes(d.file_name)
          )
          .map((d) => d.id);

        return newDocIds;
      } else {
        const errData = await res.json().catch(() => ({}));
        alert(`Upload failed (${res.status}): ${errData.detail || 'Server error'}`);
      }
    } catch (err) {
      alert(`Upload error: ${err.message}`);
    } finally {
      setIsUploading(false);
    }
    return [];
  };

  const handleSend = async (questionText = input) => {
    if ((!questionText.trim() && attachedFiles.length === 0) || isLoading) return;

    let attachmentNames = [];
    let currentDocIds = [...(activeSession?.docIds || [])];
    setIsLoading(true);

    if (attachedFiles.length > 0) {
      attachedFiles.forEach((file) => attachmentNames.push(file.name));
      const newUploadedDocIds = await uploadAndIndexFiles(attachedFiles);
      if (newUploadedDocIds.length > 0) {
        currentDocIds = Array.from(new Set([...currentDocIds, ...newUploadedDocIds]));
      }
    }

    const queryPrompt = questionText.trim() || 'Summarize the attached document(s)';
    const userMessage = {
      role: 'user',
      content: queryPrompt,
      attachments: attachmentNames,
    };

    const updatedMessages = [...messages, userMessage];
    updateActiveSession(updatedMessages, currentDocIds);

    setInput('');
    setAttachedFiles([]);

    try {
      const payload = {
        question: queryPrompt,
        history: messages.map((m) => ({ role: m.role, content: m.content })),
        top_k: topK,
        doc_ids: currentDocIds,
        model: selectedModel,
      };

      const res = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }

      const data = await res.json();
      const assistantMessage = {
        role: 'assistant',
        content: data.answer,
        sources: data.sources,
      };

      updateActiveSession([...updatedMessages, assistantMessage], currentDocIds);
    } catch (err) {
      const errorMessage = {
        role: 'assistant',
        content: `⚠️ Error: Could not generate answer (${err.message}). Make sure the API and models are running.`,
        sources: [],
      };
      updateActiveSession([...updatedMessages, errorMessage], currentDocIds);
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpenSearch = () => {
    const term = prompt("Search past conversations:");
    if (term) {
      const found = sessions.find((s) => s.title.toLowerCase().includes(term.toLowerCase()));
      if (found) setActiveSessionId(found.id);
      else alert("No conversation found.");
    }
  };

  const isHealthy = health?.status === 'healthy';
  const activeModelObj = DEFAULT_MODELS.find((m) => m.id === selectedModel) || DEFAULT_MODELS[0];

  return (
    <div className="app-container">
      {/* Sidebar */}
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        sessionDocuments={sessionDocuments}
        health={health}
        onNewChat={handleNewChat}
        onScan={fetchDocuments}
        theme={theme}
        onToggleTheme={toggleTheme}
        onOpenSearch={handleOpenSearch}
        onOpenSettings={() => setIsSettingsOpen(true)}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed((prev) => !prev)}
      />

      {/* Main Canvas */}
      <div className="chat-container">

        {/* Chat Header Bar (Upper Right Corner Model Selector & Status) */}
        <div className="chat-header-bar">
          <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>
            {activeSession?.title || 'New chat'}
          </div>

          {/* UPPER RIGHT CORNER MODEL SELECTOR & STATUS */}
          <div className="top-right-model-container">
            <div 
              className="top-right-model-pill"
              onClick={() => setShowTopRightModelDropdown((prev) => !prev)}
              title="Click to select AI Model in upper right corner"
            >
              <CheckCircle2 size={14} style={{ color: isHealthy ? '#10b981' : '#ef4444' }} />
              <Sparkles size={14} style={{ color: 'var(--accent-teal)' }} />
              <span>{activeModelObj.name}</span>
              <ChevronDown size={12} style={{ opacity: 0.6 }} />
            </div>

            {/* UPPER RIGHT MODEL DROPDOWN */}
            {showTopRightModelDropdown && (
              <div className="top-right-dropdown-menu">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 8px 6px 8px' }}>
                  <span style={{ fontSize: '0.725rem', fontWeight: 600, color: 'var(--text-muted)' }}>
                    SELECT MODEL (UPPER RIGHT)
                  </span>
                  <button 
                    className="icon-btn-ghost" 
                    onClick={() => {
                      setShowTopRightModelDropdown(false);
                      setIsSettingsOpen(true);
                    }} 
                    style={{ fontSize: '0.7rem', padding: '2px 6px', color: 'var(--accent-teal)' }}
                  >
                    Manage
                  </button>
                </div>

                {DEFAULT_MODELS.map((model) => {
                  const downloaded = isModelDownloaded(model.id);

                  return (
                    <div 
                      key={model.id}
                      className={`model-option-item ${model.id === selectedModel ? 'selected' : ''}`}
                      onClick={() => {
                        if (downloaded) {
                          setSelectedModel(model.id);
                          setShowTopRightModelDropdown(false);
                        } else {
                          if (window.confirm(`Model '${model.name}' is not downloaded yet. Open Settings to download it now?`)) {
                            setShowTopRightModelDropdown(false);
                            setIsSettingsOpen(true);
                          }
                        }
                      }}
                      style={{ opacity: downloaded ? 1 : 0.6 }}
                    >
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span>{model.name}</span>
                          <span className="model-tag-badge">{model.tag}</span>
                        </div>
                        <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)' }}>
                          {downloaded ? model.badge : 'Not Downloaded'}
                        </div>
                      </div>

                      {model.id === selectedModel ? (
                        <Check size={14} style={{ color: 'var(--accent-teal)', marginTop: '2px' }} />
                      ) : !downloaded ? (
                        <Download size={13} style={{ color: 'var(--text-muted)', marginTop: '2px' }} />
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Messages Area */}
        <div className="messages-area">
          {messages.length === 0 ? (
            <div className="empty-greeting-container">
              <div className="greeting-title">Hello there</div>
              <div className="greeting-subtitle">Type a message or upload files to get started</div>
            </div>
          ) : (
            <div className="messages-inner">
              {messages.map((msg, idx) => (
                <ChatMessage
                  key={idx}
                  message={msg}
                  onSelectSource={(source, tagNum) => {
                    setSelectedSource(source);
                    setSourceTagNumber(tagNum);
                  }}
                />
              ))}
            </div>
          )}

          {isLoading && (
            <div className="messages-inner">
              <div className="message-wrapper assistant">
                <div className="avatar-round assistant">🤖</div>
                <div className="message-body" style={{ color: 'var(--text-muted)' }}>
                  {isUploading ? 'Uploading & Indexing document...' : 'Thinking...'}
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Capsule Floating Input Box (Cleaned without Model Name) */}
        <ChatInput
          input={input}
          setInput={setInput}
          attachedFiles={attachedFiles}
          setAttachedFiles={setAttachedFiles}
          onSend={() => handleSend(input)}
          isLoading={isLoading}
          topK={topK}
          setTopK={setTopK}
        />
      </div>

      {/* Slide-over Sources Drawer */}
      {selectedSource && (
        <SourcesDrawer
          source={selectedSource}
          tagNumber={sourceTagNumber}
          onClose={() => {
            setSelectedSource(null);
            setSourceTagNumber(null);
          }}
        />
      )}

      {/* Settings & Model Management Modal */}
      {isSettingsOpen && (
        <SettingsModal
          onClose={() => setIsSettingsOpen(false)}
          installedModels={installedModels}
          onRefreshModels={fetchInstalledModels}
          topK={topK}
          setTopK={setTopK}
        />
      )}
    </div>
  );
}
