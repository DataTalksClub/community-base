(function () {
  "use strict";

  function cookie(name) {
    return document.cookie
      .split(";")
      .map(function (value) { return value.trim(); })
      .find(function (value) { return value.startsWith(name + "="); })
      ?.slice(name.length + 1) || "";
  }

  function request(url, options) {
    var settings = Object.assign({ credentials: "same-origin" }, options || {});
    settings.headers = Object.assign(
      { "Content-Type": "application/json", "X-CSRFToken": decodeURIComponent(cookie("csrftoken")) },
      settings.headers || {}
    );
    return fetch(url, settings).then(function (response) {
      if (!response.ok) throw new Error("comment_request_failed");
      return response.json();
    });
  }

  function text(tag, value) {
    var node = document.createElement(tag);
    node.textContent = value;
    return node;
  }

  function actionButton(label, action) {
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", action);
    return button;
  }

  function controller(root) {
    if (root.dataset.commentsReady === "true") return;
    root.dataset.commentsReady = "true";
    var endpoint = root.dataset.commentsUrl;
    var list = root.querySelector("[data-comment-list]");
    var authenticated = root.dataset.authenticated === "true";
    function itemUrl(template, id) { return template.replace("/0/", "/" + id + "/"); }

    function load() {
      request(endpoint).then(function (data) {
        list.replaceChildren();
        data.comments.forEach(function (comment) {
          var item = document.createElement("article");
          item.append(text("h3", comment.user_name));
          item.append(text("p", comment.body));
          if (authenticated) {
            item.append(actionButton(
              (comment.user_voted ? "Remove vote" : "Vote") + " (" + comment.vote_count + ")",
              function () { request(itemUrl(root.dataset.voteUrl, comment.id), { method: "POST" }).then(load); }
            ));
            var reply = document.createElement("form");
            var input = document.createElement("textarea");
            input.name = "body";
            input.required = true;
            reply.append(input, text("button", "Reply"));
            reply.addEventListener("submit", function (event) {
              event.preventDefault();
              request(itemUrl(root.dataset.replyUrl, comment.id), {
                method: "POST",
                body: JSON.stringify({ body: input.value })
              }).then(load);
            });
            item.append(reply);
          }
          comment.replies.forEach(function (reply) {
            var row = document.createElement("blockquote");
            row.append(text("strong", reply.user_name), text("p", reply.body));
            item.append(row);
          });
          list.append(item);
        });
      });
    }

    var form = root.querySelector("[data-comment-form]");
    if (form) form.addEventListener("submit", function (event) {
      event.preventDefault();
      var input = form.elements.body;
      request(endpoint, { method: "POST", body: JSON.stringify({ body: input.value }) })
        .then(function () { input.value = ""; load(); });
    });
    load();
  }

  document.querySelectorAll("[data-comment-thread]").forEach(controller);
})();
