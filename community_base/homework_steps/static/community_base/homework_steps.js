document.querySelectorAll("[data-homework-autosave]").forEach((form) => {
  const status = form.querySelector("[data-save-status]");
  let timer;
  let pending = Promise.resolve();
  let queued = 0;
  let dirty = false;
  let editSequence = 0;
  let submitting = false;
  const save = () => {
    queued += 1;
    status.textContent = "Saving…";
    pending = pending.then(async () => {
      const savedSequence = editSequence;
      const data = new FormData(form);
      data.set("intent", "save");
      const response = await fetch(form.dataset.saveUrl || form.action, {
        method: "POST",
        body: data,
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error(response.status === 409 ? "Changed in another tab. Reload to continue." : "Save failed. Try again.");
      const saved = await response.json();
      if (saved.saved !== true || !Number.isInteger(saved.revision) || saved.revision <= Number(data.get("revision"))) {
        throw new Error("Save failed. Try again.");
      }
      form.querySelector('[name="revision"]').value = saved.revision;
      if (editSequence === savedSequence) dirty = false;
      status.textContent = "Saved";
    }).catch((error) => {
      dirty = true;
      status.textContent = error.message.startsWith("Changed in another tab") ? error.message : "Save failed. Try again.";
    })
      .finally(() => { queued -= 1; });
    return pending;
  };
  form.addEventListener("input", () => {
    dirty = true;
    editSequence += 1;
    clearTimeout(timer);
    timer = setTimeout(save, 700);
  });
  window.addEventListener("beforeunload", (event) => {
    if (submitting || (!dirty && !queued)) return;
    event.preventDefault();
    event.returnValue = "";
  });
  form.closest(".homework-steps")?.querySelectorAll("a[href]").forEach((link) => {
    link.addEventListener("click", async (event) => {
      if (!dirty && !queued) return;
      event.preventDefault();
      clearTimeout(timer);
      timer = null;
      if (dirty) save();
      await pending;
      if (dirty && status.textContent === "Saved") await save();
      if (status.textContent === "Saved") window.location.assign(link.href);
    });
  });
  form.addEventListener("submit", async (event) => {
    if (submitting) return;
    const submitter = event.submitter;
    event.preventDefault();
    clearTimeout(timer);
    timer = null;
    await pending;
    if (dirty || (status.textContent !== "Saved" && status.textContent !== "Draft ready")) await save();
    if (status.textContent !== "Saved" && status.textContent !== "Draft ready") return;
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
