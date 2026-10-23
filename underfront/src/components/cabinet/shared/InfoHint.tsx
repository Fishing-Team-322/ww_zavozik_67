'use client'

import {
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react'
import { createPortal } from 'react-dom'
import { CircleHelp } from 'lucide-react'
import { cn } from '@/src/lib/cn'

type CurvedScrollAreaProps = {
  children: ReactNode
  className?: string
  contentClassName?: string

  radius?: number
  strokeWidth?: number
  inset?: number
  trail?: number
  minThumbSize?: number
}

/**
 * Назначение функции: Отображает компонент `CurvedScrollArea` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
function CurvedScrollArea({
  children,
  className = '',
  contentClassName = '',

  radius = 22,
  strokeWidth = 4,
  inset = 6,
  trail = 18,
  minThumbSize = 42,
}: CurvedScrollAreaProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const pathRef = useRef<SVGPathElement>(null)
  const thumbRef = useRef<SVGPathElement>(null)

  const rafRef = useRef<number | null>(null)

  const pathLengthRef = useRef(0)
  const thumbLengthRef = useRef(0)

  const [height, setHeight] = useState(1)
  const [path, setPath] = useState('')
  const [overflowing, setOverflowing] = useState(false)

  const svgWidth = Math.max(
    50,
    radius * 2 + trail + inset + strokeWidth,
  )

  const updateThumb = useCallback(() => {
    const scroll = scrollRef.current
    const thumb = thumbRef.current

    if (!scroll || !thumb) return

    const maxScroll =
      scroll.scrollHeight - scroll.clientHeight

    if (maxScroll <= 0) {
      thumb.style.strokeDashoffset = '0'
      return
    }

    const progress = Math.max(
      0,
      Math.min(1, scroll.scrollTop / maxScroll),
    )

    const travel = Math.max(
      0,
      pathLengthRef.current -
        thumbLengthRef.current,
    )

    thumb.style.strokeDashoffset = `${
      -(progress * travel)
    }`
  }, [])

  const scheduleUpdate = useCallback(() => {
    if (rafRef.current !== null) return

    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null
      updateThumb()
    })
  }, [updateThumb])

  const buildPath = useCallback(() => {
    const root = rootRef.current
    const scroll = scrollRef.current

    if (!root || !scroll) return

    const h = root.clientHeight

    if (h <= 0) return

    setHeight(h)

    const edge = inset + strokeWidth / 2

    const x =
      svgWidth -
      inset -
      strokeWidth / 2

    const r = Math.max(
      2,
      radius -
        inset -
        strokeWidth / 2,
    )

    const startX = Math.max(
      strokeWidth / 2,
      x - r - trail,
    )

    const top = edge
    const bottom = h - edge

    const d = [
      `M ${startX} ${top}`,
      `L ${x - r} ${top}`,
      `A ${r} ${r} 0 0 1 ${x} ${top + r}`,
      `L ${x} ${bottom - r}`,
      `A ${r} ${r} 0 0 1 ${x - r} ${bottom}`,
      `L ${startX} ${bottom}`,
    ].join(' ')

    setPath(d)

    setOverflowing(
      scroll.scrollHeight >
        scroll.clientHeight + 1,
    )
  }, [
    inset,
    radius,
    strokeWidth,
    svgWidth,
    trail,
  ])

  /**
   * После изменения path измеряем его
   * фактическую SVG-длину.
   */
  useLayoutEffect(() => {
    const scroll = scrollRef.current
    const pathElement = pathRef.current
    const thumb = thumbRef.current

    if (
      !scroll ||
      !pathElement ||
      !thumb ||
      !path
    ) {
      return
    }

    const hasOverflow =
      scroll.scrollHeight >
      scroll.clientHeight + 1

    setOverflowing(hasOverflow)

    if (!hasOverflow) return

    const totalLength =
      pathElement.getTotalLength()

    pathLengthRef.current = totalLength

    const visibleRatio =
      scroll.clientHeight /
      scroll.scrollHeight

    const thumbLength = Math.min(
      totalLength,
      Math.max(
        minThumbSize,
        totalLength * visibleRatio,
      ),
    )

    thumbLengthRef.current = thumbLength

    /**
     * Один dash = сам thumb.
     * Всё остальное — gap.
     */
    thumb.style.strokeDasharray =
      `${thumbLength} ${
        totalLength + thumbLength
      }`

    updateThumb()
  }, [
    path,
    minThumbSize,
    updateThumb,
  ])

  useLayoutEffect(() => {
    buildPath()
  }, [buildPath])

  useEffect(() => {
    const root = rootRef.current
    const scroll = scrollRef.current

    if (!root || !scroll) return

    const resizeObserver =
      new ResizeObserver(() => {
        buildPath()
      })

    resizeObserver.observe(root)

    const mutationObserver =
      new MutationObserver(() => {
        buildPath()
      })

    mutationObserver.observe(scroll, {
      childList: true,
      subtree: true,
      characterData: true,
    })

    scroll.addEventListener(
      'scroll',
      scheduleUpdate,
      {
        passive: true,
      },
    )

    return () => {
      resizeObserver.disconnect()
      mutationObserver.disconnect()

      scroll.removeEventListener(
        'scroll',
        scheduleUpdate,
      )

      if (rafRef.current !== null) {
        cancelAnimationFrame(
          rafRef.current,
        )
      }
    }
  }, [
    buildPath,
    scheduleUpdate,
  ])

  return (
    <div
      ref={rootRef}
      className={`
        group
        relative
        overflow-hidden
        ${className}
      `}
    >
      {/* REAL SCROLL AREA */}
      <div
        ref={scrollRef}
        className={`
          max-h-[inherit]
          w-full
          overflow-y-auto
          overscroll-contain

          [scrollbar-width:none]
          [-ms-overflow-style:none]
          [&::-webkit-scrollbar]:hidden

          ${contentClassName}
        `}
      >
        {children}
      </div>

      {/* CURVED SCROLLBAR */}
      <svg
        aria-hidden="true"
        viewBox={`0 0 ${svgWidth} ${height}`}
        preserveAspectRatio="none"
        className={`
          pointer-events-none
          absolute
          inset-y-0
          right-0
          z-50
          h-full
          overflow-visible

          transition-opacity
          duration-200

          ${
            overflowing
              ? 'opacity-100'
              : 'opacity-0'
          }
        `}
        style={{
          width: svgWidth,
        }}
      >
        {/* TRACK */}
        <path
          ref={pathRef}
          d={path}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="
            text-white/[0.04]
            opacity-0

            transition-opacity
            duration-200

            group-hover:opacity-100
          "
        />

        {/* THUMB */}
        <path
          ref={thumbRef}
          d={path}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="
            text-white/35

            transition-colors
            duration-200

            group-hover:text-white/60
          "
        />
      </svg>
    </div>
  )
}

/**
 * ОБА ВАРИАНТА ЭКСПОРТА.
 *
 * Поэтому работают:
 *
 * import CurvedScrollArea from './CurvedScrollArea'
 *
 * И:
 *
 * import { CurvedScrollArea } from './CurvedScrollArea'
 */
export { CurvedScrollArea }
export default CurvedScrollArea

/**
 * Назначение функции: Выполняет операцию `subscribeToHydration` для объекта «результат операции `subscribeToHydration`». Возвращает результат выражения: `() => {}`.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
const subscribeToHydration = () => () => {}
/**
 * Назначение функции: Выполняет операцию `clientReady` для объекта «результат операции `clientReady`». Возвращает результат выражения: `true`.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
const clientReady = () => true
/**
 * Назначение функции: Выполняет операцию `serverNotReady` для объекта «результат операции `serverNotReady`». Возвращает результат выражения: `false`.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
const serverNotReady = () => false

type InfoHintProps = {
  text?: string
  summary?: string
  title?: string
  children?: ReactNode
  label?: string
  className?: string
}

/** Non-modal documentation popover, portalled beyond table/dialog clipping. */
/**
 * Назначение функции: Non-modal documentation popover, portalled beyond table/dialog clipping.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function InfoHint({
  text,
  summary,
  title = 'Подсказка',
  children,
  label = 'Показать справку',
  className,
}: InfoHintProps) {
  const ready = useSyncExternalStore(
    subscribeToHydration,
    clientReady,
    serverNotReady,
  )
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [position, setPosition] = useState({ left: 0, top: 0 })
  const anchor = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pinned = useRef(false)
  const hintId = useId()
  const shortText =
    summary ||
    (text && text.length > 280
      ? `${text.slice(0, 240).replace(/\s+\S*$/, '')}…`
      : undefined)

  /**
   * Назначение функции: Отменяет данные объекта «значение типа `InfoHint`»; операция `cancel`.
   * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
   */
  function cancel() {
    if (timer.current) clearTimeout(timer.current)
  }

  /**
   * Назначение функции: Показывает данные объекта «значение типа `InfoHint`»; операция `show`.
   * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
   */
  function show() {
    cancel()
    setOpen(true)
  }

  /**
   * Назначение функции: Скрывает данные объекта «значение типа `InfoHint`»; операция `hide`.
   * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
   */
  function hide() {
    cancel()
    if (!pinned.current) {
      timer.current = setTimeout(() => setOpen(false), 160)
    }
  }

  const close = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    pinned.current = false
    setOpen(false)
    setExpanded(false)
  }, [])

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  useLayoutEffect(() => {
    if (!open) return

    /**
     * Назначение функции: Выполняет операцию `place` для объекта «значение типа `InfoHint`». Выполняет вызовы: `anchor.current.getBoundingClientRect`, `panel.current.getBoundingClientRect`, `Math.max`; значение не возвращает.
     * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
     */
    const place = () => {
      if (!anchor.current || !panel.current) return

      const anchorRect = anchor.current.getBoundingClientRect()
      const panelRect = panel.current.getBoundingClientRect()
      const top =
        anchorRect.bottom + 8 + panelRect.height <= window.innerHeight - 12
          ? anchorRect.bottom + 8
          : Math.max(12, anchorRect.top - panelRect.height - 8)

      setPosition({
        left: Math.max(
          12,
          Math.min(
            anchorRect.right - panelRect.width,
            window.innerWidth - panelRect.width - 12,
          ),
        ),
        top,
      })
    }

    place()
    const observer = new ResizeObserver(place)
    if (panel.current) observer.observe(panel.current)
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)

    /**
     * Назначение функции: Выполняет операцию `outside` для объекта «значение типа `InfoHint`». Выполняет вызовы: `anchor.current?.contains`, `panel.current?.contains`, `close`; значение не возвращает.
     * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
     */
    const outside = (event: PointerEvent) => {
      if (
        !anchor.current?.contains(event.target as Node) &&
        !panel.current?.contains(event.target as Node)
      ) {
        close()
      }
    }

    /**
     * Назначение функции: Экранирует данные объекта «значение типа `InfoHint`»; операция `escape`.
     * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
     */
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopImmediatePropagation()
        close()
      }
    }

    document.addEventListener('pointerdown', outside)
    window.addEventListener('keydown', escape, true)

    return () => {
      observer.disconnect()
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
      document.removeEventListener('pointerdown', outside)
      window.removeEventListener('keydown', escape, true)
    }
  }, [open, close])

  return (
    <span className={cn('inline-flex shrink-0 align-middle', className)}>
      <button
        ref={anchor}
        type="button"
        disabled={!ready}
        data-dialog-initial-focus="skip"
        aria-label={label}
        aria-expanded={open}
        aria-controls={open ? hintId : undefined}
        aria-describedby={open ? hintId : undefined}
        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text-secondary)] hover:bg-[var(--surface-subtle)] hover:text-[var(--text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={(event) => {
          if (!panel.current?.contains(event.relatedTarget as Node)) hide()
        }}
        onClick={() => {
          pinned.current = !pinned.current
          if (pinned.current) show()
          else close()
        }}
      >
        <CircleHelp size={17} aria-hidden="true" />
      </button>

      {open &&
        createPortal(
          <div
            ref={panel}
            id={hintId}
            role={shortText ? 'dialog' : 'tooltip'}
            aria-label={title}
            style={{
              ...position,
              width: `min(${expanded ? 480 : 320}px, calc(100vw - 24px))`,
            }}
            onBlur={(event) => {
              if (
                !event.currentTarget.contains(event.relatedTarget as Node) &&
                event.relatedTarget !== anchor.current
              ) {
                close()
              }
            }}
            onMouseEnter={show}
            onMouseLeave={hide}
            onMouseDown={(event) => event.stopPropagation()}
            className="motion-safe:transition-[width] motion-safe:duration-150 fixed z-[10050] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] text-left text-sm leading-6 text-[var(--text-primary)]"
          >
            <CurvedScrollArea
              className="max-h-[min(540px,calc(100dvh-24px))]"
              contentClassName="p-6 pr-12"
            >
              <div className="mb-2 text-sm font-semibold">{title}</div>
              <div className="space-y-3 text-[var(--text-secondary)] [&_strong]:font-medium [&_strong]:text-[var(--text-primary)] [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-4">
                {shortText && !expanded ? (
                  <p>{shortText}</p>
                ) : (
                  children ??
                  text
                    ?.split('\n')
                    .filter(Boolean)
                    .map((paragraph, index) => (
                      <p key={index}>{paragraph}</p>
                    ))
                )}
              </div>
              {shortText && (
                <button
                  type="button"
                  onClick={() => {
                    pinned.current = true
                    setExpanded((value) => !value)
                  }}
                  className="mt-3 rounded-sm px-2 py-1 text-sm font-medium text-[var(--accent)] hover:bg-[var(--surface-subtle)]"
                >
                  {expanded ? 'Меньше' : 'Больше'}
                </button>
              )}
            </CurvedScrollArea>
          </div>,
          document.body,
        )}
    </span>
  )
}

export const HelpTooltip = InfoHint
