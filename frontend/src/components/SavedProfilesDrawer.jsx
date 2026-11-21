import React, { useEffect, useState } from 'react';
import { Users, Save, Trash2, X, DownloadCloud } from 'lucide-react';

export default function SavedProfilesDrawer({
  isOpen,
  onClose,
  currentFormData,
  onApplyProfile,
}) {
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [profileName, setProfileName] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const loadProfiles = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/profiles');
      if (res.ok) {
        setProfiles(await res.json());
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      loadProfiles();
    }
  }, [isOpen]);

  const handleSaveProfile = async (e) => {
    e.preventDefault();
    if (!profileName.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch('/api/profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: profileName.trim(),
          data: currentFormData || {},
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Could not save profile');
      }
      setProfileName('');
      await loadProfiles();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id) => {
    try {
      const res = await fetch(`/api/profiles/${id}`, { method: 'DELETE' });
      if (res.ok) {
        setProfiles((prev) => prev.filter((p) => p.id !== id));
      }
    } catch {
      // ignore
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/50 backdrop-blur-xs flex justify-end">
      <div className="bg-white w-full max-w-md h-full shadow-2xl border-l border-slate-200 flex flex-col">
        <div className="px-5 py-4 bg-slate-900 text-white flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Users className="w-4 h-4 text-amber-400" />
            <h3 className="text-sm font-bold">Saved Data Profiles</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-slate-800 cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 border-b border-slate-200 bg-slate-50/70 space-y-3">
          <p className="text-xs text-slate-600">
            Save the current form values as a reusable profile to auto-fill any other PDF document in one click.
          </p>
          <form onSubmit={handleSaveProfile} className="flex gap-2">
            <input
              type="text"
              value={profileName}
              onChange={(e) => setProfileName(e.target.value)}
              placeholder="Profile name (e.g., Jordan Rivera)..."
              data-testid="profile-name-input"
              className="flex-1 rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-slate-900"
            />
            <button
              type="submit"
              disabled={saving || !profileName.trim()}
              data-testid="save-profile-btn"
              className="inline-flex items-center gap-1.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-amber-400 font-semibold text-xs px-3.5 py-2 transition cursor-pointer disabled:opacity-50"
            >
              <Save className="w-3.5 h-3.5" />
              Save
            </button>
          </form>
          {error && <p className="text-xs text-red-600">{error}</p>}
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-2.5">
          {loading ? (
            <p className="text-xs text-slate-500 text-center py-8">Loading saved profiles...</p>
          ) : profiles.length === 0 ? (
            <div className="text-center py-10 text-xs text-slate-400">
              No saved profiles yet. Fill a form and save it above to reuse across documents.
            </div>
          ) : (
            profiles.map((prof) => {
              const fieldCount = Object.keys(prof.data || {}).length;
              return (
                <div
                  key={prof.id}
                  className="rounded-xl border border-slate-200 bg-white p-3.5 flex items-center justify-between gap-2 hover:border-slate-300 transition"
                >
                  <div className="min-w-0">
                    <div className="text-xs font-bold text-slate-900 truncate">{prof.name}</div>
                    <div className="text-[11px] text-slate-500">
                      {fieldCount} saved field{fieldCount === 1 ? '' : 's'}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <button
                      type="button"
                      onClick={() => {
                        onApplyProfile(prof);
                        onClose();
                      }}
                      className="inline-flex items-center gap-1 text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white px-2.5 py-1.5 rounded-lg transition cursor-pointer"
                    >
                      <DownloadCloud className="w-3.5 h-3.5" />
                      Load
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(prof.id)}
                      className="p-1.5 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 transition cursor-pointer"
                      title="Delete profile"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
