(function () {
  "use strict";
  const form = document.querySelector("form.filter-bar");
  if (!form) return;
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
})();
