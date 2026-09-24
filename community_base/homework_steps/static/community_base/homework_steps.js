document.querySelectorAll("[data-homework-autosave]").forEach((form) => {
  const status = form.querySelector("[data-save-status]");
  let timer = null;
  let pending = Promise.resolve();
  let queued = 0;
  let dirty = false;
  let editSequence = 0;
  let saveFailed = false;
  let submitting = false;
  let navigating = false;

  const setStatus = (message, isError = false) => {
    status.textContent = message;
    status.setAttribute("role", isError ? "alert" : "status");
    status.setAttribute("aria-live", isError ? "assertive" : "polite");
  };

  const save = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    queued += 1;
    saveFailed = false;
    setStatus("Saving…");
    pending = pending.then(async () => {
      const savedSequence = editSequence;
      const data = new FormData(form);
      const revision = Number(data.get("revision"));
      data.set("intent", "save");
      const response = await fetch(form.dataset.saveUrl || form.action, {
        method: "POST",
        body: data,
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!response.ok) {
        if (response.status === 409) {
          throw new Error("This draft changed in another tab. Reload this page to get the latest version before leaving.");
        }
        if (response.status === 403) {
          throw new Error("This homework no longer accepts saves. Keep this page open and copy your latest answer before leaving.");
        }
        throw new Error("Your latest edits could not be saved. Check your connection, then retry before leaving this page.");
      }
      const saved = await response.json();
      if (saved.saved !== true || !Number.isInteger(saved.revision) || saved.revision <= revision) {
        throw new Error("Your latest edits could not be saved. Retry before leaving this page.");
      }
      form.querySelector('[name="revision"]').value = saved.revision;
      if (editSequence === savedSequence) dirty = false;
      setStatus(dirty ? "Saving your latest changes…" : "Saved");
    }).catch((error) => {
      dirty = true;
      saveFailed = true;
      setStatus(error.message, true);
    }).finally(() => {
      queued -= 1;
    });
    return pending;
  };

  const scheduleSave = () => {
    dirty = true;
    editSequence += 1;
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(save, 700);
  };

  const flush = async () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    // A settled failure from an earlier autosave is retried when the learner
    // chooses a same-tab destination again. A request that fails while this
    // flush is waiting blocks this navigation without an immediate retry.
    if (saveFailed && queued === 0) saveFailed = false;
    await pending;
    if (saveFailed) return false;

    while (dirty || queued > 0 || timer !== null) {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      if (dirty && queued === 0) save();
      await pending;
      if (saveFailed) return false;
    }
    return !dirty && queued === 0;
  };

  form.addEventListener("input", scheduleSave);

  window.addEventListener("beforeunload", (event) => {
    if (submitting || (!dirty && !queued && timer === null)) return;
    event.preventDefault();
    event.returnValue = "";
  });

  document.addEventListener("click", async (event) => {
    const link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented) return;
    if (!link.closest(".homework-steps, [data-homework-autosave-nav]")) return;
    if (
      event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey ||
      link.hasAttribute("download") ||
      (link.target && link.target.toLowerCase() !== "_self")
    ) return;
    if (!dirty && !queued && timer === null) return;
    event.preventDefault();
    if (navigating) return;
    navigating = true;
    const href = link.href;
    if (await flush()) window.location.assign(href);
    navigating = false;
  });

  form.addEventListener("submit", async (event) => {
    if (submitting) return;
    const submitter = event.submitter;
    event.preventDefault();
    const saved = await flush();
    if (!saved && status.getAttribute("role") === "alert") return;
    if (dirty || (status.textContent !== "Saved" && status.textContent !== "Draft ready")) {
      await save();
    }
    if (status.getAttribute("role") === "alert") return;
    if (submitter?.name) {
      const field = document.createElement("input");
      field.type = "hidden";
      field.name = submitter.name;
      field.value = submitter.value;
      form.append(field);
    }
    if (!form.reportValidity()) return;
    submitting = true;
    HTMLFormElement.prototype.submit.call(form);
  });
});
