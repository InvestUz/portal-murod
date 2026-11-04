import {useEffect} from 'react';
import {EditorContent,useEditor,useEditorState} from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import {Bold,Italic,List,ListOrdered} from 'lucide-react';
import {usePortal} from './context';

/** Runs only in the browser. HTML is sanitized again by the Python API. */
export default function RichEditor({value,onChange,required=false}:{value:string;onChange:(value:string)=>void;required?:boolean}) {
  const {t}=usePortal();
  const editor=useEditor({immediatelyRender:false,extensions:[StarterKit.configure({link:false,heading:false,codeBlock:false,code:false,horizontalRule:false})],content:value,
    editorProps:{attributes:{class:'rich-editor-content',role:'textbox','aria-multiline':'true','aria-label':t('body'),'aria-required':String(required)}},
    onUpdate:({editor})=>onChange(editor.isEmpty?'':editor.getHTML())});
  useEffect(()=>{if(editor&&!editor.isDestroyed&&editor.getHTML()!==value&&!(editor.isEmpty&&!value))editor.commands.setContent(value,{emitUpdate:false});},[editor,value]);
  const state=useEditorState({editor,selector:({editor})=>({bold:editor&&!editor.isDestroyed&&editor.isActive('bold'),italic:editor&&!editor.isDestroyed&&editor.isActive('italic'),bullet:editor&&!editor.isDestroyed&&editor.isActive('bulletList'),ordered:editor&&!editor.isDestroyed&&editor.isActive('orderedList')})});
  return <div className="rich-editor"><div className="editor-toolbar" role="toolbar" aria-label={t('body')}>
    <button type="button" className="icon-button" aria-label={t('bold')} aria-pressed={!!state?.bold} onClick={()=>editor?.chain().focus().toggleBold().run()}><Bold size={17}/></button>
    <button type="button" className="icon-button" aria-label={t('italic')} aria-pressed={!!state?.italic} onClick={()=>editor?.chain().focus().toggleItalic().run()}><Italic size={17}/></button>
    <button type="button" className="icon-button" aria-label={t('bulletList')} aria-pressed={!!state?.bullet} onClick={()=>editor?.chain().focus().toggleBulletList().run()}><List size={17}/></button>
    <button type="button" className="icon-button" aria-label={t('numberedList')} aria-pressed={!!state?.ordered} onClick={()=>editor?.chain().focus().toggleOrderedList().run()}><ListOrdered size={17}/></button>
  </div><EditorContent editor={editor}/></div>;
}
