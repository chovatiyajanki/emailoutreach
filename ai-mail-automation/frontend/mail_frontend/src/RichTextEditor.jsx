import React, { useRef, useEffect, useState, useCallback } from 'react'

/**
 * Converts plain text or HTML string into standardized HTML paragraphs
 */
export const ensureHtmlContent = (val) => {
  if (!val) return '<p><br></p>'
  // If it already contains HTML tags, return as is
  if (/<(p|div|br|b|i|u|h1|h2|h3|ul|ol|li|blockquote|a)[\s>]/i.test(val)) {
    return val
  }
  // Otherwise convert newlines to paragraphs
  const paragraphs = val.split(/\n\n+/)
  return paragraphs
    .map((p) => `<p>${p.replace(/\n/g, '<br>')}</p>`)
    .join('')
}

export default function RichTextEditor({
  value = '',
  onChange,
  placeholder = 'Compose your email message body...',
  minHeight = '240px',
}) {
  const editorRef = useRef(null)
  const textareaRef = useRef(null)
  const [viewMode, setViewMode] = useState('visual') // 'visual' | 'code'
  const [wordCount, setWordCount] = useState(0)
  const [charCount, setCharCount] = useState(0)
  const savedSelectionRef = useRef(null)
  const isUpdatingRef = useRef(false)

  // Save current cursor selection in contentEditable
  const saveSelection = () => {
    const sel = window.getSelection()
    if (sel && sel.rangeCount > 0 && editorRef.current) {
      const range = sel.getRangeAt(0)
      if (editorRef.current.contains(range.commonAncestorContainer)) {
        savedSelectionRef.current = range.cloneRange()
      }
    }
  }

  // Restore cursor selection
  const restoreSelection = () => {
    const sel = window.getSelection()
    if (sel && savedSelectionRef.current && editorRef.current) {
      try {
        sel.removeAllRanges()
        sel.addRange(savedSelectionRef.current)
      } catch {
        // Fallback: move cursor to end of editor
        const range = document.createRange()
        range.selectNodeContents(editorRef.current)
        range.collapse(false)
        sel.removeAllRanges()
        sel.addRange(range)
      }
    }
  }

  // Calculate word and character count
  const updateMetrics = useCallback((html) => {
    const tmp = document.createElement('div')
    tmp.innerHTML = html || ''
    const text = tmp.innerText || tmp.textContent || ''
    setCharCount(text.length)
    const words = text.trim() ? text.trim().split(/\s+/).length : 0
    setWordCount(words)
  }, [])

  // Sync internal editor content when external value prop changes
  useEffect(() => {
    const currentHtml = viewMode === 'visual'
      ? (editorRef.current ? editorRef.current.innerHTML : '')
      : (textareaRef.current ? textareaRef.current.value : '')

    const formattedValue = ensureHtmlContent(value)

    if (formattedValue !== currentHtml && !isUpdatingRef.current) {
      if (editorRef.current) {
        editorRef.current.innerHTML = formattedValue
      }
      if (textareaRef.current) {
        textareaRef.current.value = formattedValue
      }
      updateMetrics(formattedValue)
    }
  }, [value, viewMode, updateMetrics])

  // Handle content changes in visual editor
  const handleEditorInput = () => {
    if (!editorRef.current) return
    isUpdatingRef.current = true
    const html = editorRef.current.innerHTML
    updateMetrics(html)
    if (onChange) {
      onChange(html)
    }
    setTimeout(() => {
      isUpdatingRef.current = false
    }, 50)
  }

  // Handle content changes in code editor
  const handleTextareaChange = (e) => {
    const val = e.target.value
    updateMetrics(val)
    if (onChange) {
      onChange(val)
    }
  }

  // Execute standard formatting commands
  const executeCmd = (command, value = null) => {
    if (viewMode === 'code') return
    editorRef.current?.focus()
    restoreSelection()
    document.execCommand(command, false, value)
    handleEditorInput()
  }

  // Insert link prompt
  const handleInsertLink = () => {
    if (viewMode === 'code') return
    const sel = window.getSelection()
    const selectedText = sel ? sel.toString() : ''
    const url = window.prompt('Enter Destination URL:', 'https://')
    if (url && url !== 'https://' && url.trim()) {
      if (!selectedText) {
        executeCmd('insertHTML', `<a href="${url.trim()}" target="_blank" rel="noopener noreferrer">${url.trim()}</a>`)
      } else {
        executeCmd('createLink', url.trim())
      }
    }
  }

  // Toggle between WYSIWYG Visual and HTML Code view
  const handleToggleViewMode = (newMode) => {
    if (newMode === viewMode) return
    if (newMode === 'code') {
      const html = editorRef.current ? editorRef.current.innerHTML : value
      if (textareaRef.current) textareaRef.current.value = html
    } else {
      const html = textareaRef.current ? textareaRef.current.value : value
      if (editorRef.current) editorRef.current.innerHTML = html
    }
    setViewMode(newMode)
  }

  return (
    <div className="react-rich-text-editor">
      {/* ====================================================================
          TOP TOOLBAR: FORMATTING CONTROLS & VARIABLE TAGS
          ==================================================================== */}
      <div className="rte-toolbar">
        {/* Style block selector */}
        <select
          className="rte-select"
          disabled={viewMode === 'code'}
          defaultValue="p"
          onChange={(e) => {
            const val = e.target.value
            if (val === 'p' || val === 'blockquote') {
              executeCmd('formatBlock', val)
            } else {
              executeCmd('formatBlock', val)
            }
          }}
          title="Text Style"
        >
          <option value="p">Paragraph</option>
          <option value="h2">Heading 2</option>
          <option value="h3">Heading 3</option>
          <option value="blockquote">Quote</option>
        </select>

        <span className="rte-divider" />

        {/* Text Styling */}
        <button
          type="button"
          className="rte-btn"
          disabled={viewMode === 'code'}
          onMouseDown={(e) => { e.preventDefault(); executeCmd('bold'); }}
          title="Bold (Ctrl+B)"
        >
          <strong>B</strong>
        </button>

        <button
          type="button"
          className="rte-btn"
          disabled={viewMode === 'code'}
          onMouseDown={(e) => { e.preventDefault(); executeCmd('italic'); }}
          title="Italic (Ctrl+I)"
        >
          <em>I</em>
        </button>

        <button
          type="button"
          className="rte-btn"
          disabled={viewMode === 'code'}
          onMouseDown={(e) => { e.preventDefault(); executeCmd('underline'); }}
          title="Underline (Ctrl+U)"
        >
          <u>U</u>
        </button>

        <button
          type="button"
          className="rte-btn"
          disabled={viewMode === 'code'}
          onMouseDown={(e) => { e.preventDefault(); executeCmd('strikeThrough'); }}
          title="Strikethrough"
        >
          <s>S</s>
        </button>

        <span className="rte-divider" />

        {/* Lists */}
        <button
          type="button"
          className="rte-btn"
          disabled={viewMode === 'code'}
          onMouseDown={(e) => { e.preventDefault(); executeCmd('insertUnorderedList'); }}
          title="Bulleted List"
        >
          • List
        </button>

        <button
          type="button"
          className="rte-btn"
          disabled={viewMode === 'code'}
          onMouseDown={(e) => { e.preventDefault(); executeCmd('insertOrderedList'); }}
          title="Numbered List"
        >
          1. List
        </button>

        <span className="rte-divider" />

        {/* Alignment */}
        <button
          type="button"
          className="rte-btn"
          disabled={viewMode === 'code'}
          onMouseDown={(e) => { e.preventDefault(); executeCmd('justifyLeft'); }}
          title="Align Left"
        >
          ⯸ Left
        </button>

        <button
          type="button"
          className="rte-btn"
          disabled={viewMode === 'code'}
          onMouseDown={(e) => { e.preventDefault(); executeCmd('justifyCenter'); }}
          title="Align Center"
        >
          ⯹ Center
        </button>

        <span className="rte-divider" />

        {/* Link Insertion */}
        <button
          type="button"
          className="rte-btn"
          disabled={viewMode === 'code'}
          onMouseDown={(e) => { e.preventDefault(); handleInsertLink(); }}
          title="Insert Link"
        >
          🔗 Link
        </button>

        {/* Clear Formatting */}
        <button
          type="button"
          className="rte-btn"
          disabled={viewMode === 'code'}
          onMouseDown={(e) => { e.preventDefault(); executeCmd('removeFormat'); }}
          title="Clear Formatting"
        >
          🧹 Clean
        </button>

        {/* Undo / Redo */}
        <button
          type="button"
          className="rte-btn"
          disabled={viewMode === 'code'}
          onMouseDown={(e) => { e.preventDefault(); executeCmd('undo'); }}
          title="Undo"
        >
          ↺
        </button>

        <button
          type="button"
          className="rte-btn"
          disabled={viewMode === 'code'}
          onMouseDown={(e) => { e.preventDefault(); executeCmd('redo'); }}
          title="Redo"
        >
          ↻
        </button>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '4px' }}>
          {/* Mode Switcher */}
          <button
            type="button"
            className={`rte-mode-btn ${viewMode === 'visual' ? 'active' : ''}`}
            onClick={() => handleToggleViewMode('visual')}
            title="Visual WYSIWYG Editor"
          >
            👁️ Visual
          </button>
          <button
            type="button"
            className={`rte-mode-btn ${viewMode === 'code' ? 'active' : ''}`}
            onClick={() => handleToggleViewMode('code')}
            title="Edit Raw HTML Code"
          >
            &lt;/&gt; HTML
          </button>
        </div>
      </div>


      {/* ====================================================================
          EDITOR CANVAS: VISUAL CONTENTEDITABLE OR RAW HTML TEXTAREA
          ==================================================================== */}
      <div className="rte-canvas-container" style={{ minHeight }}>
        {viewMode === 'visual' ? (
          <div
            ref={editorRef}
            className="rte-contenteditable"
            contentEditable
            suppressContentEditableWarning
            onInput={handleEditorInput}
            onKeyUp={saveSelection}
            onMouseUp={saveSelection}
            onFocus={saveSelection}
            data-placeholder={placeholder}
            style={{ minHeight }}
          />
        ) : (
          <textarea
            ref={textareaRef}
            className="rte-code-textarea"
            onChange={handleTextareaChange}
            placeholder="Edit HTML source code directly..."
            style={{ minHeight }}
          />
        )}
      </div>

      {/* ====================================================================
          FOOTER METRICS BAR
          ==================================================================== */}
      <div className="rte-footer">
        <span className="rte-footer-hint">
          {viewMode === 'visual'
            ? '💡 Use formatting controls above or paste styled copy directly.'
            : '💡 Raw HTML Mode: Standard <b>, <i>, <a>, <ul>, <p> tags supported.'}
        </span>
        <div className="rte-metrics">
          <span>{wordCount} words</span>
          <span>•</span>
          <span>{charCount} characters</span>
        </div>
      </div>
    </div>
  )
}
