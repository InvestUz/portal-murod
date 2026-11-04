// A deliberate browser-language choice survives login and MFA transitions.
export function readLocalePreference(read:()=>string|null):'uz'|'ru'|'en'|null{
  try{const value=read();return value==='ru'||value==='uz'||value==='en'?value:null;}catch{return null;}
}
export function chooseLocale(preference:'uz'|'ru'|'en'|null,account:'uz'|'ru'|'en'):'uz'|'ru'|'en'{
  return preference??account;
}
