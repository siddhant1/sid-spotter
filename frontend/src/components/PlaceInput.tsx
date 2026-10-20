import { useEffect, useId, useRef, useState } from 'react'
import { geocode } from '../api'
import type { Place } from '../types'

interface Props {
  label: string
  value: Place | null
  onChange: (p: Place | null) => void
  placeholder?: string
}

export default function PlaceInput({ label, value, onChange, placeholder }: Props) {
  const [text, setText] = useState(value?.label ?? '')
  const [results, setResults] = useState<Place[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [loading, setLoading] = useState(false)
  const listId = useId()
  const typed = useRef(false)
  const clearedByTyping = useRef(false)

  // Keep the text in sync when the parent sets the place (swap, examples),
  // but not when the place was cleared because the user started typing.
  useEffect(() => {
    if (value == null && clearedByTyping.current) {
      clearedByTyping.current = false
      return
    }
    typed.current = false
    setText(value?.label ?? '')
  }, [value])

  useEffect(() => {
    if (!typed.current || text.trim().length < 2) {
      setResults([])
      return
    }
    const ctrl = new AbortController()
    const t = setTimeout(() => {
      setLoading(true)
      geocode(text, ctrl.signal)
        .then((r) => {
          setResults(r)
          setActive(0)
          setOpen(true)
        })
        .catch(() => {})
        .finally(() => setLoading(false))
    }, 250)
    return () => {
      clearTimeout(t)
      ctrl.abort()
    }
  }, [text])

  const choose = (p: Place) => {
    onChange(p)
    setOpen(false)
  }

  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <div className="combo">
        <input
          type="text"
          value={text}
          placeholder={placeholder}
          role="combobox"
          aria-expanded={open && results.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          onChange={(e) => {
            typed.current = true
            setText(e.target.value)
            if (value) {
              clearedByTyping.current = true
              onChange(null)
            }
          }}
          onFocus={() => results.length && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (!open || !results.length) return
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setActive((a) => (a + 1) % results.length)
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setActive((a) => (a - 1 + results.length) % results.length)
            } else if (e.key === 'Enter') {
              e.preventDefault()
              choose(results[active])
            } else if (e.key === 'Escape') setOpen(false)
          }}
        />
        {loading && <span className="combo-spinner" aria-hidden />}
        {open && results.length > 0 && (
          <ul className="combo-list" id={listId} role="listbox">
            {results.map((r, i) => (
              <li
                key={`${r.lat},${r.lon}`}
                role="option"
                aria-selected={i === active}
                className={i === active ? 'is-active' : ''}
                onMouseDown={(e) => {
                  e.preventDefault()
                  choose(r)
                }}
                onMouseEnter={() => setActive(i)}
              >
                {r.label}
              </li>
            ))}
          </ul>
        )}
      </div>
    </label>
  )
}
