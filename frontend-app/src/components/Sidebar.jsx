import React, { useState } from 'react';
import { 
  Plus, 
  MessageSquare, 
  Trash2, 
  Edit3, 
  Database, 
  Terminal, 
  LogOut, 
  LogIn, 
  ShieldCheck, 
  PanelLeftClose, 
  Zap, 
  Check, 
  X,
  Search,
  TrendingUp
} from 'lucide-react';

export default function Sidebar({
  isOpen,
  onToggle,
  chats,
  activeChatId,
  onSelectChat,
  onNewChat,
  onDeleteChat,
  onRenameChat,
  currentUser,
  activeView,
  setActiveView,
  onOpenAuth,
  onLogout,
  onOpenWatchlist
}) {
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const isAdmin = currentUser?.role === 'admin';

  const startRename = (chat, e) => {
    e.stopPropagation();
    setEditingId(chat.id);
    setEditTitle(chat.title);
  };

  const saveRename = (chatId, e) => {
    e.stopPropagation();
    if (editTitle.trim()) {
      onRenameChat(chatId, editTitle.trim());
    }
    setEditingId(null);
  };

  const cancelRename = (e) => {
    e.stopPropagation();
    setEditingId(null);
  };

  const handleDelete = (chatId, e) => {
    e.stopPropagation();
    if (confirm('Delete this conversation?')) {
      onDeleteChat(chatId);
    }
  };

  // Filter chats by search
  const filteredChats = chats.filter(c => 
    c.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div 
          onClick={onToggle}
          className="md:hidden fixed inset-0 z-40 bg-black/70 backdrop-blur-sm"
        />
      )}

      {/* Sidebar Container */}
      <aside
        className={`fixed md:static inset-y-0 left-0 z-50 flex flex-col w-64 bg-[#08090e] border-r border-white/5 transition-transform duration-300 ease-in-out ${
          isOpen ? 'translate-x-0' : '-translate-x-full md:hidden'
        }`}
      >
        {/* Top Header */}
        <div className="p-3 border-b border-white/5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[#ff6600] to-[#b34700] p-0.5 flex items-center justify-center glow-orange-sm">
              <div className="w-full h-full bg-[#050508] rounded-[5px] flex items-center justify-center">
                <Zap className="w-3.5 h-3.5 text-[#ff6600]" />
              </div>
            </div>
            <span className="font-bold text-xs tracking-tight text-white font-mono uppercase">
              Nifty Financial Rag
            </span>
          </div>

          <button
            onClick={onToggle}
            title="Collapse sidebar"
            className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        </div>

        {/* New Chat Button */}
        <div className="p-3 pb-2 space-y-2">
          <button
            onClick={onNewChat}
            className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl bg-[#0c0d14] hover:bg-[#151722] border border-orange-500/20 hover:border-orange-500/50 text-white text-xs font-semibold transition-all shadow-sm group"
          >
            <span className="flex items-center gap-2">
              <Plus className="w-4 h-4 text-[#ff6600] group-hover:scale-110 transition-transform" />
              New chat
            </span>
            <span className="text-[10px] text-gray-500 font-mono">Ctrl+N</span>
          </button>

          <button
            onClick={onOpenWatchlist}
            className="w-full flex items-center justify-between px-3 py-2 rounded-xl bg-[#0c0d14] hover:bg-[#151722] border border-white/5 hover:border-orange-500/30 text-gray-300 hover:text-white text-xs font-semibold transition-all group"
          >
            <span className="flex items-center gap-2">
              <TrendingUp className="w-3.5 h-3.5 text-[#ff6600] group-hover:scale-110 transition-transform" />
              Stock Watchlist
            </span>
            <span className="px-1.5 py-0.5 rounded bg-orange-500/10 text-[#ff6600] font-mono text-[10px] font-bold">
              Concalls
            </span>
          </button>
        </div>

        {/* Search input if multiple chats */}
        {chats.length > 4 && (
          <div className="px-3 pb-2">
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search conversations..."
                className="w-full pl-7 pr-3 py-1.5 bg-[#050508] border border-white/5 rounded-lg text-[11px] text-gray-300 placeholder-gray-500 focus:outline-none focus:border-orange-500/40"
              />
              <Search className="w-3 h-3 text-gray-500 absolute left-2 top-2" />
            </div>
          </div>
        )}

        {/* Recent Chats List */}
        <div className="flex-1 overflow-y-auto px-2 space-y-1">
          <div className="px-2 py-1.5 text-[10px] font-mono font-semibold uppercase tracking-wider text-gray-500">
            Recent Chats ({filteredChats.length})
          </div>

          {filteredChats.map((chat) => {
            const isActive = chat.id === activeChatId;
            return (
              <div
                key={chat.id}
                onClick={() => onSelectChat(chat.id)}
                className={`group relative flex items-center justify-between px-2.5 py-2 rounded-xl text-xs cursor-pointer transition-all ${
                  isActive
                    ? 'bg-orange-500/10 text-white font-medium border-l-2 border-[#ff6600]'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-white/[0.03]'
                }`}
              >
                <div className="flex items-center gap-2 overflow-hidden pr-2">
                  <MessageSquare className={`w-3.5 h-3.5 flex-shrink-0 ${isActive ? 'text-[#ff6600]' : 'text-gray-500'}`} />
                  
                  {editingId === chat.id ? (
                    <input
                      type="text"
                      value={editTitle}
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') saveRename(chat.id, e);
                        if (e.key === 'Escape') cancelRename(e);
                      }}
                      className="w-32 bg-[#050508] border border-orange-500/50 rounded px-1.5 py-0.5 text-xs text-white focus:outline-none"
                    />
                  ) : (
                    <span className="truncate">{chat.title}</span>
                  )}
                </div>

                {/* Hover Action Buttons */}
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                  {editingId === chat.id ? (
                    <>
                      <button
                        onClick={(e) => saveRename(chat.id, e)}
                        className="p-1 hover:text-emerald-400 text-gray-400"
                      >
                        <Check className="w-3 h-3" />
                      </button>
                      <button
                        onClick={cancelRename}
                        className="p-1 hover:text-red-400 text-gray-400"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={(e) => startRename(chat, e)}
                        title="Rename"
                        className="p-1 hover:text-white text-gray-500 transition-colors"
                      >
                        <Edit3 className="w-3 h-3" />
                      </button>
                      <button
                        onClick={(e) => handleDelete(chat.id, e)}
                        title="Delete"
                        className="p-1 hover:text-red-400 text-gray-500 transition-colors"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}

          {filteredChats.length === 0 && (
            <div className="px-3 py-6 text-center text-xs text-gray-500">
              No chats found.
            </div>
          )}
        </div>

        {/* Sidebar Footer: Profile & Workspace Switcher */}
        <div className="p-3 border-t border-white/5 space-y-2 bg-[#050508]/60">
          
          {/* Admin Workspace Toggle */}
          {isAdmin && (
            <div className="flex items-center gap-1 p-1 bg-[#0c0d14] rounded-xl border border-white/5">
              <button
                onClick={() => setActiveView('chat')}
                className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-[11px] font-semibold transition-all ${
                  activeView === 'chat'
                    ? 'bg-[#ff6600] text-white shadow-sm glow-orange-sm'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                <Terminal className="w-3 h-3" />
                Terminal
              </button>
              <button
                onClick={() => setActiveView('admin')}
                className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-[11px] font-semibold transition-all ${
                  activeView === 'admin'
                    ? 'bg-[#ff6600] text-white shadow-sm glow-orange-sm'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                <Database className="w-3 h-3" />
                Admin
              </button>
            </div>
          )}

          {/* User Profile Card */}
          {currentUser ? (
            <div className="flex items-center justify-between p-2 rounded-xl bg-[#0c0d14] border border-white/5">
              <div className="flex items-center gap-2 overflow-hidden">
                <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-orange-600 to-amber-500 flex items-center justify-center text-xs font-bold text-white flex-shrink-0">
                  {currentUser.username?.[0]?.toUpperCase() || 'U'}
                </div>
                <div className="truncate">
                  <div className="text-xs font-semibold text-white truncate">
                    {currentUser.name || currentUser.username}
                  </div>
                  <div className={`text-[10px] font-mono font-bold ${
                    currentUser.role === 'admin' ? 'text-[#ff6600]' : 'text-emerald-400'
                  }`}>
                    {currentUser.role?.toUpperCase()}
                  </div>
                </div>
              </div>

              <button
                onClick={onLogout}
                title="Sign out"
                className="p-1.5 rounded-lg text-gray-400 hover:text-red-400 hover:bg-white/5 transition-colors"
              >
                <LogOut className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : (
            <button
              onClick={onOpenAuth}
              className="w-full flex items-center justify-center gap-2 py-2 rounded-xl bg-[#ff6600] hover:bg-[#e65c00] text-white text-xs font-semibold transition-all shadow-md glow-orange-sm"
            >
              <LogIn className="w-3.5 h-3.5" />
              Log in to Terminal
            </button>
          )}

        </div>
      </aside>
    </>
  );
}
