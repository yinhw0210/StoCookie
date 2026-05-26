// contentScript.js
let clickLoopActive = false;
let selectedElementPath = '';

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'startClickLoop') {
    clickLoopActive = true;
    clickLoop();
  }
});

// 用户选择元素时的处理函数
document.addEventListener('click', event => {
  const path = getElementPath(event.target);
  selectedElementPath = path;
  chrome.runtime.sendMessage({ action: 'updatePopup', path });
});

// 获取元素的路径
function getElementPath(element) {
  let path = [];
  while (element && element !== document.body) {
    let index = Array.from(element.parentNode.children).indexOf(element) + 1;
    path.unshift(`${element.tagName.toLowerCase()}:${index}`);
    element = element.parentNode;
  }
  return path.join('>');
}

// 定时刷新并点击
async function clickLoop() {
  while (clickLoopActive) {
    await refreshPage();
    await clickElement(selectedElementPath);
    await new Promise(resolve => setTimeout(resolve, 5000)); // 例如，每5秒执行一次
  }
}

// 刷新页面
async function refreshPage() {
  return new Promise((resolve) => {
    chrome.tabs.reload(undefined, {}, resolve);
  });
}

// 根据路径点击元素
async function clickElement(path) {
  const steps = path.split('>');
  let element = document;
  for (const step of steps) {
    const [tagName, index] = step.split(':');
    element = Array.from(element.getElementsByTagName(tagName))[parseInt(index) - 1];
  }
  if (element) {
    element.click();
  } else {
    console.error('Element not found.');
  }
}