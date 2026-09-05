(function () {
  "use strict";

  const root = document.querySelector("[data-voting-root]");
  if (!root) return;

  function csrfToken() {
    const row = document.cookie.split(";").map((value) => value.trim()).find((value) => value.startsWith("csrftoken="));
    return row ? decodeURIComponent(row.slice("csrftoken=".length)) : "";
  }

  async function send(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken()},
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Request failed");
    return data;
  }

  root.querySelectorAll("[data-vote-button]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const card = button.closest("[data-option-id]");
        const data = await send(root.dataset.voteUrl, {option_id: card.dataset.optionId});
        const voted = data.action === "voted";
        button.dataset.voted = voted ? "true" : "false";
        button.textContent = voted ? "Voted" : "Vote";
        button.classList.toggle("cb-button-primary", voted);
        card.querySelector("[data-vote-count]").textContent = String(data.vote_count);
        const remaining = root.querySelector("[data-votes-remaining]");
        if (remaining) remaining.textContent = String(data.votes_remaining);
      } catch (error) {
        window.alert(error.message);
      } finally {
        button.disabled = false;
      }
    });
  });

  const form = root.querySelector("[data-proposal-form]");
  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const message = form.querySelector("[data-proposal-message]");
      const values = new FormData(form);
      try {
        await send(root.dataset.proposeUrl, {title: values.get("title"), description: values.get("description")});
        message.textContent = "Proposal submitted. Reload the page to see it.";
        message.hidden = false;
        form.reset();
      } catch (error) {
        message.textContent = error.message;
        message.hidden = false;
      }
    });
  }
})();
