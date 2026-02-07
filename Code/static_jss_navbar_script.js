/* Kai Singer */

function updateCrane() {
  const mast = document.querySelector('.mast');
  mast.replaceChildren();
  const screenHeight = window.innerHeight - 260;
  const segmentHeight = 29;
  const numSegments = Math.max(10, Math.ceil(screenHeight / segmentHeight));

  for (let i = 0; i < numSegments; i++) {
    const segment = document.createElement('img');
    segment.src = `${staticImgsPrefix}crane_segment.png`;
    segment.classList.add('crane_segment');
    segment.style.top = (159 + i * segmentHeight) + 'px';
    segment.draggable = false;
    mast.appendChild(segment);
  }

  const base = document.createElement('img');
  base.src = `${staticImgsPrefix}crane_base.png`;
  base.classList.add('crane_base');
  base.style.top = (159 + numSegments * segmentHeight) + 'px';
  base.draggable = false;
  mast.appendChild(base);
}

window.addEventListener('DOMContentLoaded', updateCrane);
window.addEventListener('resize', updateCrane);

const menu = document.querySelector('.menu_items');
const items = document.querySelectorAll('.menu_item');
const highlight = document.querySelector('.highlight');
const string = document.querySelector('.string');

let activeIndex = 0;
for (let i = 0; i < items.length; i++) {
  if (items[i].classList.contains('selected')) {
    activeIndex = i;
    break;
  }
}

function moveHighlightTo(index) {
  const item = items[index];
  const itemTop = item.offsetTop;
  const itemHeight = item.offsetHeight;

  highlight.style.top = itemTop + 'px';
  highlight.style.height = itemHeight + 'px';

  string.style.height = itemTop + 'px';
}

moveHighlightTo(activeIndex);

items.forEach((item, index) => {
  item.addEventListener('mouseenter', () => moveHighlightTo(index));
});

menu.addEventListener('mouseleave', () => moveHighlightTo(activeIndex));

document.addEventListener("DOMContentLoaded", () => {
  const usermenuButton = document.querySelector('.usermenu_show_button');
  const usermenu = document.querySelector('.usermenu');

  usermenuButton.addEventListener('click', () => {
    usermenu.classList.toggle('shown');
  });
});

const navbarHideButton = document.querySelector(".navbar_hide_button");
const navbarShowButton = document.querySelector(".navbar_show_button");
const navbar = document.querySelector(".navbar");

if (window.innerWidth <= 768) {
  navbar.classList.add("hidden");
  navbar.classList.remove("shown");
} else {
  navbar.classList.remove("hidden");
  navbar.classList.add("shown");
}

navbarHideButton.addEventListener("click", () => {
  navbar.classList.remove("hover_effect");
  navbar.classList.add("hidden");
  navbar.classList.remove("shown");
});

navbarShowButton.addEventListener("click", () => {
  navbar.classList.remove("hidden");
  navbar.classList.add("shown");
  setTimeout(() => {
    navbar.classList.add("hover_effect");
  }, 500);
});