/* Sidebar section preferences for the shared Studio shell.

   These helpers touch no DOM at load time, so the collapse rules can be
   exercised without a browser. Storage may be absent, blocked or hold
   something other than the object written last time; every entry point
   degrades to the server-rendered state instead of throwing. */
(function (root) {
  var STORAGE_KEY = 'community-base-studio-nav';

  function readPreferences(storage) {
    try {
      var parsed = JSON.parse((storage && storage.getItem(STORAGE_KEY)) || '{}');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
      return parsed;
    } catch (error) {
      return {};
    }
  }

  function writePreference(storage, key, expanded) {
    try {
      var preferences = readPreferences(storage);
      preferences[key] = !!expanded;
      storage.setItem(STORAGE_KEY, JSON.stringify(preferences));
      return true;
    } catch (error) {
      return false;
    }
  }

  function resolveExpanded(preferences, key, serverExpanded, activeSection) {
    if (key && key === activeSection) return true;
    var preferred = preferences ? preferences[key] : undefined;
    return typeof preferred === 'boolean' ? preferred : !!serverExpanded;
  }

  root.studioNav = {
    STORAGE_KEY: STORAGE_KEY,
    readPreferences: readPreferences,
    writePreference: writePreference,
    resolveExpanded: resolveExpanded
  };
})(typeof window !== 'undefined' ? window : globalThis);
