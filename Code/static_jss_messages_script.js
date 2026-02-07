/* Kai Singer */

document.addEventListener("DOMContentLoaded", () => {
  console.log("Document loaded");
  const messages = document.getElementsByClassName("message");
  for (let i = 0; i < messages.length; i++) {
    messages[i].classList.remove("hidden");
    setTimeout(() => {
      messages[i].classList.add("hidden");
      setTimeout(() => messages[0].remove(), 500);
    }, 5000);
  }
});