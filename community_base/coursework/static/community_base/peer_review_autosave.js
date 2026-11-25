// Autosave for a peer-review form (community_base.coursework.peer_review_form.autosave).
// Markup contract: <form data-peer-review-autosave data-autosave-url="..."> with a
// [data-save-status] element inside. Each save POSTs the form with action=draft and
// X-Requested-With: XMLHttpRequest; the endpoint answers {saved} or {submitted}.
(function () {
  document.querySelectorAll("form[data-peer-review-autosave][data-autosave-url]").forEach(function (form) {
    var status = form.querySelector("[data-save-status]");
    var stopped = false;
    var timer = null;
    var inflight = null;
    var dirty = false;
    function show(text) { if (status && !stopped) status.textContent = text; }
    function save() {
      clearTimeout(timer);
      if (!dirty || stopped) return;
      if (inflight) { timer = setTimeout(save, 300); return; }
      dirty = false;
      show("Saving…");
      var data = new FormData(form);
      data.set("action", "draft");
      inflight = fetch(form.getAttribute("data-autosave-url"), {
        method: "POST", body: data, credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      }).then(function (r) { return r.json().then(function (j) { return [r, j]; }); })
        .then(function (res) {
          if (res[0].ok && res[1].saved) show("Draft saved");
          else if (res[1].submitted) { stopped = true; }
          else show("Could not save. Use Submit to keep your answers.");
        })
        .catch(function () { show("Could not save. Use Submit to keep your answers."); })
        .then(function () { inflight = null; });
    }
    function schedule(delay) { dirty = true; clearTimeout(timer); timer = setTimeout(save, delay); }
    form.addEventListener("change", function () { schedule(0); });
    form.addEventListener("input", function (e) { if (e.target.tagName === "TEXTAREA") schedule(800); });
    form.addEventListener("focusout", function (e) { if (e.target.tagName === "TEXTAREA") save(); });
  });
})();
