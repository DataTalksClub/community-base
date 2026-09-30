// The shared project submission form (coursework/_project_submission_form.html).
// Progressive enhancement only: without JavaScript the form still posts the saved links plus
// one blank slot, and Remove submits without a confirmation.
document.querySelectorAll("[data-project-form]").forEach((form) => {
  form.querySelectorAll("[data-learning-in-public-links]").forEach((group) => {
    const maxLinks = Number.parseInt(group.dataset.maxLinks, 10);
    const slots = group.querySelector("[data-learning-in-public-slots]");
    const addButton = group.querySelector("[data-add-learning-in-public-link]");
    if (!slots || !addButton || !Number.isFinite(maxLinks) || maxLinks < 1) {
      return;
    }
    const inputs = () => slots.querySelectorAll("input[type='url']");
    const refresh = () => {
      const full = inputs().length >= maxLinks;
      addButton.hidden = full;
      addButton.disabled = full;
    };
    addButton.addEventListener("click", () => {
      const existing = inputs();
      if (existing.length >= maxLinks) return;
      const template = existing[existing.length - 1];
      const input = template ? template.cloneNode(false) : document.createElement("input");
      input.type = "url";
      input.value = "";
      input.removeAttribute("id");
      slots.append(input);
      input.focus();
      refresh();
    });
    refresh();
  });

  const commitId = form.querySelector("[data-project-field='commit_id'] input");
  if (commitId) {
    commitId.addEventListener("blur", () => {
      commitId.value = commitId.value.trim();
    });
  }

  form.querySelectorAll("[data-project-remove]").forEach((button) => {
    button.addEventListener("click", (event) => {
      const question = button.dataset.confirm;
      if (question && !window.confirm(question)) event.preventDefault();
    });
  });
});
