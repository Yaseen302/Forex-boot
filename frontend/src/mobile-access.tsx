import {useEffect,useState} from 'react';
import './mobile-access.css';

type InstallPrompt=Event & {prompt:()=>Promise<void>;userChoice:Promise<{outcome:'accepted'|'dismissed'}>};

export function MobileAccess(){
 const [prompt,setPrompt]=useState<InstallPrompt>(),[notice,setNotice]=useState(''),[online,setOnline]=useState(navigator.onLine);
 const installed=window.matchMedia('(display-mode: standalone)').matches;
 const loopback=['localhost','127.0.0.1','::1','[::1]'].includes(window.location.hostname);
 const secure=window.location.protocol==='https:';
 useEffect(()=>{
  const before=(event:Event)=>{event.preventDefault();setPrompt(event as InstallPrompt)};
  const connectivity=()=>setOnline(navigator.onLine);
  window.addEventListener('beforeinstallprompt',before);window.addEventListener('online',connectivity);window.addEventListener('offline',connectivity);
  return()=>{window.removeEventListener('beforeinstallprompt',before);window.removeEventListener('online',connectivity);window.removeEventListener('offline',connectivity)};
 },[]);
 async function install(){
  if(!prompt)return;
  try{await prompt.prompt();const answer=await prompt.userChoice;setNotice(answer.outcome==='accepted'?'Home-screen installation accepted. Keep the Windows MT5 bridge running.':'You can add the terminal later from your browser menu.');setPrompt(undefined)}
  catch{setNotice('Use your browser menu to add ForexLab to the home screen.')}
 }
 async function copyAddress(){try{await navigator.clipboard.writeText(window.location.origin);setNotice('Private address copied. Each device still needs the session token.')}catch{setNotice('Copy the private HTTPS address from the browser address bar.')}}
 return <details className="mobile-access"><summary>Phone access & home-screen app</summary>
 <p>The phone is a dashboard. Your Windows PC or VPS runs MT5 and the bot; keep it on and connected.</p>
 {!online&&<p role="status" className="mobile-network-warning">This device is offline. Reconnect before trusting new data or sending controls. Broker positions remain in MT5.</p>}
 {loopback?<div className="mobile-access-note"><strong>This address works on this PC only.</strong><p>Typing 127.0.0.1 on a phone opens the phone itself. Connect the PC and phone to the same private Tailscale network, then use the private HTTPS address created by Tailscale Serve.</p></div>:<div className="mobile-access-note"><strong>{secure?'Private HTTPS address':'HTTPS setup required for phone installation'}</strong><p>{window.location.origin}</p>{secure&&<button onClick={copyAddress}>Copy this address</button>}</div>}
 <ol><li>On Windows: install/sign in to Tailscale and keep ForexLab running.</li><li>Run the included <code>scripts\enable-mobile.ps1</code> helper. It checks local readiness before creating a private HTTPS route.</li><li>Install Tailscale on your Android/iPhone and sign in to the same private network.</li><li>Open the HTTPS address printed on the PC. Enter the session token privately.</li><li>Android Chrome: menu → Add to Home screen / Install app. iPhone Safari: Share → Add to Home Screen.</li></ol>
 {installed?<p className="mobile-installed">Running in home-screen app mode.</p>:prompt&&<button className="primary" onClick={install}>Install ForexLab on this device</button>}
 <p className="mobile-access-small">Setup guide: <code>docs/MOBILE.md</code>. Installation adds a web app, not the native MetaTrader 5 app. It needs the network and the running Windows bridge. This version serves one account per backend; other users should connect their own separate Windows installation.</p>
 {notice&&<p role="status">{notice}</p>}
 </details>;
}
