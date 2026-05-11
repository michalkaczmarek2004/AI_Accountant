(function () {
  "use strict";
  const form = document.querySelector("form.filter-bar");
  if (form) {
    const submit = () => form.submit();
    form.querySelectorAll("select").forEach((el) => el.addEventListener("change", submit));
    let qTimer = null;
    const qInput = form.querySelector('input[name="q"]');
    if (qInput) {
      qInput.addEventListener("input", () => {
        clearTimeout(qTimer);
        qTimer = setTimeout(submit, 400);
      });
    }
  }
})();

(function () {
  "use strict";
  const storagePrefix = "ai-accountant:ack:v1:";
  const keyFor = (id) => `${storagePrefix}${id}`;

  const isAcked = (id) => {
    try {
      return window.localStorage.getItem(keyFor(id)) === "1";
    } catch (_err) {
      return false;
    }
  };

  const setAcked = (id) => {
    try {
      window.localStorage.setItem(keyFor(id), "1");
    } catch (_err) {
      // localStorage can be unavailable in hardened browser settings.
    }
  };

  const clearAcked = (id) => {
    try {
      window.localStorage.removeItem(keyFor(id));
    } catch (_err) {
      // localStorage can be unavailable in hardened browser settings.
    }
  };

  const sortDeadlineList = (list) => {
    Array.from(list.querySelectorAll("[data-ack-kind='deadline']"))
      .sort((a, b) => {
        const aConfirmed = a.getAttribute("data-ack-confirmed") === "true";
        const bConfirmed = b.getAttribute("data-ack-confirmed") === "true";
        if (aConfirmed !== bConfirmed) {
          return aConfirmed ? 1 : -1;
        }
        return Number(a.dataset.ackOrder || 0) - Number(b.dataset.ackOrder || 0);
      })
      .forEach((item) => list.appendChild(item));
  };

  const sortDeadlineLists = () => {
    document.querySelectorAll(".deadline-list").forEach(sortDeadlineList);
  };

  document.querySelectorAll("[data-ack-kind='deadline']").forEach((item, index) => {
    item.dataset.ackOrder = String(index);
    const status = item.querySelector("[data-ack-status]");
    if (status) {
      status.dataset.originalText = status.textContent || "";
      status.dataset.originalClass = status.className || "";
    }
  });

  const markDeadlineConfirmed = (item) => {
    item.hidden = false;
    item.classList.add("confirmed");
    item.setAttribute("data-ack-confirmed", "true");
    const status = item.querySelector("[data-ack-status]");
    if (status) {
      status.hidden = true;
    }
    const button = item.querySelector("[data-ack-button]");
    if (button) {
      button.textContent = "Confirmed";
      button.setAttribute("aria-pressed", "true");
      button.title = "Move back to active deadlines";
    }
    sortDeadlineLists();
  };

  const unmarkDeadlineConfirmed = (item) => {
    item.classList.remove("confirmed");
    item.removeAttribute("data-ack-confirmed");
    const status = item.querySelector("[data-ack-status]");
    if (status) {
      status.hidden = false;
      status.textContent = status.dataset.originalText || status.textContent;
      status.className = status.dataset.originalClass || status.className;
    }
    const button = item.querySelector("[data-ack-button]");
    if (button) {
      button.textContent = "Mark as done";
      button.setAttribute("aria-pressed", "false");
      button.removeAttribute("title");
    }
    sortDeadlineLists();
  };

  const applyAckedItems = () => {
    document.querySelectorAll("[data-ack-item]").forEach((item) => {
      const id = item.getAttribute("data-ack-id");
      if (!id || !isAcked(id)) return;
      if (item.getAttribute("data-ack-kind") === "deadline") {
        markDeadlineConfirmed(item);
      } else {
        item.hidden = true;
      }
    });
  };

  const updateAckScopes = () => {
    document.querySelectorAll("[data-ack-scope]").forEach((scope) => {
      const active = Array.from(scope.querySelectorAll("[data-ack-kind='deadline']")).filter(
        (item) => item.getAttribute("data-ack-confirmed") !== "true"
      );
      const counter = scope.querySelector("[data-ack-count]");
      if (counter) {
        counter.textContent = String(active.length);
      }
      const empty = scope.querySelector(".ack-empty");
      if (empty) {
        empty.hidden = scope.querySelectorAll("[data-ack-kind='deadline']").length !== 0;
      }
    });
  };

  applyAckedItems();
  updateAckScopes();

  document.querySelectorAll("[data-ack-button]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.getAttribute("data-ack-id");
      if (!id) return;
      const clickedItem = button.closest("[data-ack-item]");
      if (clickedItem && clickedItem.getAttribute("data-ack-kind") === "deadline") {
        if (clickedItem.getAttribute("data-ack-confirmed") === "true") {
          clearAcked(id);
          unmarkDeadlineConfirmed(clickedItem);
        } else {
          setAcked(id);
          markDeadlineConfirmed(clickedItem);
        }
      } else {
        setAcked(id);
        document.querySelectorAll("[data-ack-item]").forEach((item) => {
          if (item.getAttribute("data-ack-id") === id) {
            if (item.getAttribute("data-ack-kind") === "deadline") {
              markDeadlineConfirmed(item);
            } else {
              item.hidden = true;
            }
          }
        });
      }
      updateAckScopes();
    });
  });
})();
