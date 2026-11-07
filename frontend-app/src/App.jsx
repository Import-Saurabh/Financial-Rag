import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ChatView from './components/ChatView';
import AdminDashboard from './components/AdminDashboard';
import AuthModal from './components/AuthModal';
import SourceDrawer from './components/SourceDrawer';
import WatchlistModal from './components/WatchlistModal';

const STORAGE_USER_KEY = 'nifty_user';
const STORAGE_TOKEN_KEY = 'nifty_auth_token';

// Helper to get user-scoped chat storage key
const getChatStorageKey = (user) => {
  const username = user?.username ? user.username.toLowerCase().trim() : 'guest';
  return `nifty_rag_chats_v2_${username}`;
};

export default function App() {
  const [currentUser, setCurrentUser] = useState(null);
  const [activeView, setActiveView] = useState('chat'); // 'chat' or 'admin'
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isAuthOpen, setIsAuthOpen] = useState(false);
  const [isWatchlistOpen, setIsWatchlistOpen] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState('auto');
  const [selectedSource, setSelectedSource] = useState(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Chat sessions state
  const [chats, setChats] = useState([]);
  const [activeChatId, setActiveChatId] = useState(null);

  // Load chats for a specific user (from server and scoped localStorage)
  const loadUserChats = async (user) => {
    const storageKey = getChatStorageKey(user);
    let loadedChats = [];

    // 1. Try local storage first for instant render
    const local = localStorage.getItem(storageKey);
    if (local) {
      try {
        const parsed = JSON.parse(local);
        if (Array.isArray(parsed) && parsed.length > 0) {
          loadedChats = parsed;
        }
      } catch (e) {
        console.error('Failed to parse local chats:', e);
      }
    }

    // 2. If user is logged in, sync with server
    const token = localStorage.getItem(STORAGE_TOKEN_KEY);
    if (user && token) {
      try {
        const res = await fetch('/api/user/chats', {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data.chats) && data.chats.length > 0) {
            loadedChats = data.chats;
            localStorage.setItem(storageKey, JSON.stringify(data.chats));
          }
        }
      } catch (err) {
        console.warn('Could not sync chats from server:', err);
      }
    }

    // 3. Fallback to default fresh chat if empty
    if (loadedChats.length === 0) {
      const defaultChat = {
        id: 'chat_' + Date.now(),
        title: 'New chat',
        messages: [],
        createdAt: Date.now()
      };
      loadedChats = [defaultChat];
      localStorage.setItem(storageKey, JSON.stringify(loadedChats));
    }

    setChats(loadedChats);
    setActiveChatId(loadedChats[0].id);
  };

  // Initialize user and their chats on mount
  useEffect(() => {
    const savedUserStr = localStorage.getItem(STORAGE_USER_KEY);
    const token = localStorage.getItem(STORAGE_TOKEN_KEY);
    let initialUser = null;

    if (savedUserStr && token) {
      try {
        initialUser = JSON.parse(savedUserStr);
        setCurrentUser(initialUser);
      } catch (e) {
        localStorage.removeItem(STORAGE_USER_KEY);
      }
    }

    loadUserChats(initialUser);
  }, []);

  // Save chats whenever chats update (to user-scoped localStorage and server)
  const saveChats = (newChats) => {
    setChats(newChats);
    const storageKey = getChatStorageKey(currentUser);
    try {
      localStorage.setItem(storageKey, JSON.stringify(newChats));
    } catch (e) {
      console.error('Failed to save chats to storage:', e);
    }

    // Sync to server if authenticated
    const token = localStorage.getItem(STORAGE_TOKEN_KEY);
    if (currentUser && token) {
      fetch('/api/user/chats', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ chats: newChats })
      }).catch(err => console.warn('Server chat sync failed:', err));
    }
  };

  const activeChat = chats.find(c => c.id === activeChatId) || chats[0] || { messages: [] };

  const handleNewChat = () => {
    const newChat = {
      id: 'chat_' + Date.now(),
      title: 'New chat',
      messages: [],
      createdAt: Date.now()
    };
    const updated = [newChat, ...chats];
    saveChats(updated);
    setActiveChatId(newChat.id);
    setActiveView('chat');
  };

  const handleSelectChat = (chatId) => {
    setActiveChatId(chatId);
    setActiveView('chat');
  };

  const handleDeleteChat = (chatId) => {
    const remaining = chats.filter(c => c.id !== chatId);
    if (remaining.length === 0) {
      const freshChat = {
        id: 'chat_' + Date.now(),
        title: 'New chat',
        messages: [],
        createdAt: Date.now()
      };
      saveChats([freshChat]);
      setActiveChatId(freshChat.id);
    } else {
      saveChats(remaining);
      if (activeChatId === chatId) {
        setActiveChatId(remaining[0].id);
      }
    }

    // Also delete on server
    const token = localStorage.getItem(STORAGE_TOKEN_KEY);
    if (currentUser && token) {
      fetch(`/api/user/chats/${chatId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      }).catch(e => console.warn('Delete chat failed on server:', e));
    }
  };

  const handleRenameChat = (chatId, newTitle) => {
    const updated = chats.map(c => 
      c.id === chatId ? { ...c, title: newTitle } : c
    );
    saveChats(updated);
  };

  const handleSendMessage = async (queryText) => {
    if (!queryText.trim() || loading) return;

    const userMsg = {
      id: Date.now().toString(),
      role: 'user',
      content: queryText.trim(),
    };

    // Auto update chat title on first message
    const currentMessages = activeChat.messages || [];
    let updatedTitle = activeChat.title;
    if (currentMessages.length === 0 || activeChat.title === 'New chat') {
      updatedTitle = queryText.length > 30 ? queryText.slice(0, 30) + '...' : queryText;
    }

    const newMessages = [...currentMessages, userMsg];

    // Optimistically update chat
    const updatedChats = chats.map(c => 
      c.id === activeChatId 
        ? { ...c, title: updatedTitle, messages: newMessages, updatedAt: Date.now() }
        : c
    );
    saveChats(updatedChats);

    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: queryText.trim(),
          provider: selectedProvider || 'auto',
          doc_type: 'both',
        }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned ${response.status}`);
      }

      const data = await response.json();

      const assistantMsg = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: data.answer || 'No response returned from the synthesis pipeline.',
        model_used: data.model_used || 'Nifty Financial RAG Engine',
        latency_sec: data.latency_sec || 0,
        chunks_used: data.chunks_used || 0,
        sql_rows: data.sql_rows || 0,
        sources: data.sources || [],
        charts: data.charts || [],
      };

      const finalMessages = [...newMessages, assistantMsg];
      const finalizedChats = chats.map(c => 
        c.id === activeChatId 
          ? { ...c, title: updatedTitle, messages: finalMessages, updatedAt: Date.now() }
          : c
      );
      saveChats(finalizedChats);

    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem(STORAGE_TOKEN_KEY);
    localStorage.removeItem(STORAGE_USER_KEY);
    setCurrentUser(null);
    setActiveView('chat');
    loadUserChats(null); // Switch to clean guest chats
  };

  const handleAuthSuccess = (user) => {
    setCurrentUser(user);
    loadUserChats(user); // Load this specific user's chat history
    if (user.role === 'admin') {
      setActiveView('admin');
    } else {
      setActiveView('chat');
    }
  };

  const handleSelectSource = (src) => {
    setSelectedSource(src);
    setIsDrawerOpen(true);
  };

  const handleQueryStock = (symbol, query) => {
    handleNewChat();
    setTimeout(() => {
      handleSendMessage(query);
    }, 150);
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#050508] text-gray-100 font-sans selection:bg-[#ff6600] selection:text-white">
      
      {/* ChatGPT-style Collapsible Left Sidebar */}
      <Sidebar
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        chats={chats}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChat}
        onNewChat={handleNewChat}
        onDeleteChat={handleDeleteChat}
        onRenameChat={handleRenameChat}
        currentUser={currentUser}
        activeView={activeView}
        setActiveView={setActiveView}
        onOpenAuth={() => setIsAuthOpen(true)}
        onLogout={handleLogout}
        onOpenWatchlist={() => setIsWatchlistOpen(true)}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        {activeView === 'admin' && currentUser?.role === 'admin' ? (
          <div className="flex-1 overflow-y-auto">
            <AdminDashboard currentUser={currentUser} />
          </div>
        ) : (
          <ChatView
            messages={activeChat.messages || []}
            onSendMessage={handleSendMessage}
            loading={loading}
            error={error}
            onSelectSource={handleSelectSource}
            selectedProvider={selectedProvider}
            setSelectedProvider={setSelectedProvider}
            onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
            onNewChat={handleNewChat}
            onOpenWatchlist={() => setIsWatchlistOpen(true)}
          />
        )}
      </div>

      {/* ChatGPT-style Clean Authentication Modal */}
      <AuthModal
        isOpen={isAuthOpen}
        onClose={() => setIsAuthOpen(false)}
        onAuthSuccess={handleAuthSuccess}
      />

      {/* Personal Corporate Concall & Filing Watchlist Modal */}
      <WatchlistModal
        isOpen={isWatchlistOpen}
        onClose={() => setIsWatchlistOpen(false)}
        currentUser={currentUser}
        onQueryStock={handleQueryStock}
        onOpenAuth={() => {
          setIsWatchlistOpen(false);
          setIsAuthOpen(true);
        }}
      />

      {/* Source Grounding Document Page Viewer (Slide-out Left Side Drawer) */}
      <SourceDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        source={selectedSource}
      />

    </div>
  );
}
