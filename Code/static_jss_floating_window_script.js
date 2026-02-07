/* Kai Singer */

function openWindow(windowId) {
  document.getElementById('fw_' + windowId).classList.add('shown');
  document.body.classList.add("no-scroll");
}

function closeWindow(windowId) {
  document.getElementById('fw_' + windowId).classList.remove('shown');
  document.body.classList.remove("no-scroll");
}

window.onclick = function(event) {
  const modals = document.getElementsByClassName('floating_bg');
  for (let i = 0; i < modals.length; i++) {
    if (event.target == modals[i]) {
      modals[i].classList.remove('shown');
      document.body.classList.remove("no-scroll");
    }
  }
}