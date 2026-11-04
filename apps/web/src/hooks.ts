import {useEffect,useState,useCallback} from 'react';
import {api,ApiError} from './api';
export function useDebounce<T>(value:T,delay=300):T{const[result,setResult]=useState(value);useEffect(()=>{const id=setTimeout(()=>setResult(value),delay);return()=>clearTimeout(id);},[value,delay]);return result;}
export function useData<T>(path:string|null){
  const[data,setData]=useState<T|null>(null),[loading,setLoading]=useState(!!path),[error,setError]=useState<ApiError|null>(null),[revision,setRevision]=useState(0);
  useEffect(()=>{if(!path){setData(null);setLoading(false);return;}const controller=new AbortController();setLoading(true);setError(null);api<T>(path,'GET',undefined,controller.signal).then(setData).catch(e=>{if(e.name!=='AbortError')setError(e instanceof ApiError?e:new ApiError('NETWORK_ERROR',0));}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});return()=>controller.abort();},[path,revision]);
  return{data,loading,error,reload:useCallback(()=>setRevision(x=>x+1),[]),setData};
}
