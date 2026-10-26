/* Account gate. Passwords never enter localStorage, URLs, logs or model inputs. */
const TrialTrustAuth = (() => {
  const el = id => document.getElementById(id);
  let token = null, browserToken = null, currentUser = null, mode = "login", busy = false;
  let legacyAvailable = false, browserRegistered = false, recoveryCode = "", receiptKind = "register", receiptUsername = "", resolveReady;
  const readyPromise = new Promise(resolve => { resolveReady = resolve; });
  try { token = sessionStorage.getItem("trialtrust-account-token"); browserToken = localStorage.getItem("trialtrust-browser-token"); } catch {}
  function headers() { return {...(token ? {"X-TrialTrust-Account":token} : {})}; }
  function forget() { token=null; try {sessionStorage.removeItem("trialtrust-account-token");}catch{} }
  function adopt(result) {
    currentUser=result.user;
    if(result.account_token){token=result.account_token;try{sessionStorage.setItem("trialtrust-account-token",token);}catch{}}
  }
  async function request(path,body) {
    const h={"Content-Type":"application/json","X-TrialTrust-Client":"web",...headers()};
    if(browserToken)h["X-TrialTrust-Browser"]=browserToken;
    if(path==="/api/auth/bootstrap" || path==="/api/auth/register"){
      let old;try{old=sessionStorage.getItem("trialtrust-session")||localStorage.getItem("trialtrust-session");}catch{}
      if(old)h["X-TrialTrust-Session"]=old;
    }
    const response=await fetch(path,{method:"POST",headers:h,body:JSON.stringify(body)});
    let result;try{result=await response.json();}catch{throw new Error("连接暂未完成，请刷新后重试。");}
    if(!response.ok)throw new Error(typeof result.detail==="string"?result.detail:"请检查输入内容后重试。");
    return result;
  }
  function setMode(value){
    mode=value; el("auth-password").type="password";el("auth-show-password").textContent="显示";el("auth-show-password").setAttribute("aria-label","显示密码");el("auth-show-password").setAttribute("aria-pressed","false"); el("auth-error").textContent=""; el("auth-receipt").hidden=true; el("auth-form").hidden=false;
    el("auth-title").textContent=value==="register"?"创建你的彩排舱":value==="recover"?"找回你的账号":"欢迎回来";
    el("auth-subtitle").textContent=value==="register"?"一个账号，保存每一次探索。":value==="recover"?"用保存的恢复码设置新密码。":"登录后，接着上一次的探索。";
    el("auth-confirm-field").hidden=value==="login";el("auth-confirm").required=value!=="login";
    el("auth-recovery-field").hidden=value!=="recover";el("auth-recovery").required=value==="recover";
    el("auth-import-field").hidden=value!=="register"||!legacyAvailable;
    el("auth-browser-note").hidden=value!=="register";
    el("auth-password-label").textContent=value==="recover"?"新密码":"密码";
    el("auth-password").autocomplete=value==="login"?"current-password":"new-password";
    el("auth-password").value="";el("auth-confirm").value="";el("auth-recovery").value="";
    el("auth-login-tab").setAttribute("aria-pressed",String(value==="login"));
    el("auth-register-tab").setAttribute("aria-pressed",String(value==="register"));
    el("auth-submit").textContent=value==="register"?"注册并启航 →":value==="recover"?"重设密码":"登录彩排舱 →";
    el("auth-submit").disabled=busy || (value==="register"&&browserRegistered);
    if(value==="register"&&browserRegistered)el("auth-error").textContent="此浏览器已经注册过账号，请登录已有账号；忘记密码可使用恢复码。";
  }
  function enter(){
    recoveryCode="";el("auth-recovery-code").value="";el("auth-form").reset();
    el("auth-gate").hidden=true;el("authenticated-app").hidden=false;
    el("account-name").textContent=currentUser?.username||"我的账号";
    resolveReady(currentUser);
  }
  function receipt(result,kind){
    recoveryCode=result.recovery_code;receiptKind=kind;receiptUsername=el("auth-username").value;
    el("auth-form").reset();el("auth-form").hidden=true;el("auth-receipt").hidden=false;
    el("auth-recovery-code").value=recoveryCode;
    el("auth-enter").textContent=kind==="register"?"我已保存，进入工作台 →":"我已保存，返回登录 →";
  }
  el("auth-login-tab").onclick=()=>{if(!busy)setMode("login");};
  el("auth-register-tab").onclick=()=>{if(!busy)setMode("register");};
  el("auth-recover-tab").onclick=()=>{if(!busy)setMode("recover");};
  el("auth-show-password").onclick=()=>{const visible=el("auth-password").type==="password";el("auth-password").type=visible?"text":"password";el("auth-show-password").textContent=visible?"隐藏":"显示";el("auth-show-password").setAttribute("aria-label",visible?"隐藏密码":"显示密码");el("auth-show-password").setAttribute("aria-pressed",String(visible));};
  el("auth-form").onsubmit=async event=>{
    event.preventDefault();if(busy)return;
    const password=el("auth-password").value;
    if(new TextEncoder().encode(password).length>72){el("auth-error").textContent="密码UTF-8编码不能超过72字节；中文会占多个字节。";return;}
    if(mode!=="login"&&password!==el("auth-confirm").value){el("auth-error").textContent="两次密码不一致。";return;}
    busy=true;el("auth-submit").disabled=true;el("auth-error").textContent="";
    const requested=mode;
    const body={username:el("auth-username").value,password};
    if(mode!=="login")body.confirm_password=el("auth-confirm").value;
    if(mode==="register")body.import_history=el("auth-import").checked;
    if(mode==="recover")body.recovery_code=el("auth-recovery").value.trim();
    try{
      const result=await request("/api/auth/"+mode,body);
      if(mode==="recover"){forget();receipt(result,"recover");}
      else {adopt(result);if(mode==="register"){browserRegistered=true;receipt(result,"register");}else enter();}
    }catch(error){el("auth-error").textContent=error.message;}
    finally{busy=false;el("auth-submit").disabled=requested==="register"&&browserRegistered;}
  };
  el("auth-enter").onclick=()=>{if(receiptKind==="register")enter();else{recoveryCode="";el("auth-recovery-code").value="";setMode("login");}};
  el("auth-download-recovery").onclick=()=>{
    const blob=new Blob(["试托账号恢复凭证\n用户名："+receiptUsername+"\n恢复码："+recoveryCode+"\n请安全保管，不要分享。\n"],{type:"text/plain;charset=utf-8"});
    const url=URL.createObjectURL(blob);const link=document.createElement("a");link.href=url;link.download="trialtrust-recovery.txt";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  el("account-logout").onclick=async()=>{
    if(busy)return;busy=true;el("account-logout").disabled=true;
    try{await request("/api/auth/logout",{});forget();window.location.reload();}
    catch(error){el("account-logout").disabled=false;busy=false;el("notice-text").textContent=error.message;el("notice").hidden=false;}
  };
  el("account-settings").onclick=()=>{el("account-password-form").reset();el("account-error").textContent="";el("account-dialog").showModal();};
  el("account-close").onclick=()=>el("account-dialog").close();
  el("account-password-form").onsubmit=async event=>{
    event.preventDefault();el("account-password-submit").disabled=true;el("account-error").textContent="";
    try{await request("/api/auth/password",{current_password:el("account-old-password").value,new_password:el("account-new-password").value});forget();window.location.reload();}
    catch(error){el("account-error").textContent=error.message;}
    finally{el("account-password-submit").disabled=false;}
  };
  async function initialize(){
    try{
      const result=await request("/api/auth/bootstrap",{});
      if(result.browser_token){browserToken=result.browser_token;try{localStorage.setItem("trialtrust-browser-token",browserToken);}catch{}}
      legacyAvailable=result.legacy_available;browserRegistered=result.browser_registered;
      if(result.authenticated){currentUser=result.user;enter();}
      else{forget();setMode("login");}
    }catch(error){el("auth-error").textContent=error.message;el("auth-submit").textContent="连接失败，请刷新重试";}
  }
  initialize();
  return {ready:()=>readyPromise,headers,user:()=>currentUser,expire:()=>{forget();window.location.reload();}};
})();
