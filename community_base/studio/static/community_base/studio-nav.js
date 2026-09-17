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

  /* Search results arrive as {group: [item]}, the same shape the sidebar groups
     destinations in. Turn them into an ordered, non-empty list of labelled
     groups; the group key is a provider name, so derive a readable header from
     it rather than keeping a map the package would have to guess. */
  function groupLabel(key) {
    var text = String(key || '').replace(/[_-]+/g, ' ').trim();
    if (!text) return 'Results';
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function searchGroups(payload) {
    var groups = (payload && payload.results) || {};
    if (typeof groups !== 'object' || Array.isArray(groups)) return [];
    return Object.keys(groups)
      .map(function (key) {
        var items = Array.isArray(groups[key]) ? groups[key].filter(Boolean) : [];
        return {key: key, label: groupLabel(key), items: items};
      })
      .filter(function (group) {
        return group.items.length > 0;
      });
  }

  root.studioNav = {
    STORAGE_KEY: STORAGE_KEY,
    readPreferences: readPreferences,
    writePreference: writePreference,
    resolveExpanded: resolveExpanded,
    groupLabel: groupLabel,
    searchGroups: searchGroups
  };
})(typeof window !== 'undefined' ? window : globalThis);
