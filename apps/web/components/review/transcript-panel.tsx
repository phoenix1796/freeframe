'use client'

import * as React from 'react'
import useSWR from 'swr'
import { FileText, Loader2, AlertCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useReviewStore } from '@/stores/review-store'

interface TranscriptWord {
  text: string
  start: number
  end: number
}

interface TranscriptUrlData {
  url: string | null
  error: string | null
}

interface TranscriptPanelProps {
  assetId: string
  versionId: string | null
  transcriptRequested: boolean
  /** Only project owners can trigger transcription — each request is a real
   * cost against the transcription provider. */
  isOwner: boolean
}

function EmptyState({ text, action }: { text: string; action?: React.ReactNode }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="h-12 w-12 rounded-full bg-bg-tertiary flex items-center justify-center">
        <FileText className="h-6 w-6 text-text-tertiary/50" />
      </div>
      <p className="text-xs text-text-tertiary">{text}</p>
      {action}
    </div>
  )
}

/** Read-only transcript view: click a word to seek the video there.
 * No active-word playback sync (yet) — deliberately kept simple, since
 * subscribing to playheadTime here would re-render the whole word list
 * up to ~4x/sec during playback. */
export function TranscriptPanel({ assetId, versionId, transcriptRequested, isOwner }: TranscriptPanelProps) {
  const seekTo = useReviewStore((s) => s.seekTo)
  const [requesting, setRequesting] = React.useState(false)
  // Optimistic — the parent's transcriptRequested prop only updates on the
  // next versions refetch, so reflect the just-sent request immediately.
  const [justRequested, setJustRequested] = React.useState(false)
  const effectivelyRequested = transcriptRequested || justRequested

  const { data: urlData, mutate: mutateUrl } = useSWR<TranscriptUrlData>(
    effectivelyRequested && versionId ? `/assets/${assetId}/transcript?version_id=${versionId}` : null,
    (key: string) => api.get<TranscriptUrlData>(key),
    // Transcription is a short-lived background job — poll until it lands
    // (or fails — either way there's nothing more to wait for).
    { refreshInterval: (data) => (data?.url || data?.error ? 0 : 5000) },
  )

  const { data: transcript } = useSWR<{ words: TranscriptWord[] }>(
    urlData?.url ?? null,
    (url: string) => fetch(url).then((r) => r.json()),
  )

  const triggerTranscript = async () => {
    if (!versionId) return
    setRequesting(true)
    try {
      await api.post(`/assets/${assetId}/transcript?version_id=${versionId}`, {})
      setJustRequested(true)
      // The backend clears any previous error on this same call — reflect
      // that immediately instead of showing the stale error until the next
      // poll (up to 5s away).
      mutateUrl({ url: null, error: null }, { revalidate: false })
    } catch {
      // Silent fail — the button stays put so they can retry.
    } finally {
      setRequesting(false)
    }
  }

  if (effectivelyRequested && urlData?.error) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 p-6 text-center">
        <div className="h-12 w-12 rounded-full bg-status-error/10 flex items-center justify-center">
          <AlertCircle className="h-6 w-6 text-status-error" />
        </div>
        <p className="text-xs text-text-secondary">{urlData.error}</p>
        {isOwner && (
          <Button size="sm" variant="secondary" onClick={triggerTranscript} disabled={requesting}>
            {requesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Try again'}
          </Button>
        )}
      </div>
    )
  }

  if (!effectivelyRequested) {
    return (
      <EmptyState
        text={isOwner ? 'No transcript yet for this version.' : 'No transcript yet. Ask a project owner to generate one.'}
        action={
          isOwner && (
            <Button size="sm" onClick={triggerTranscript} disabled={requesting || !versionId}>
              {requesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Create transcript'}
            </Button>
          )
        }
      />
    )
  }

  if (!urlData?.url) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-2 p-6 text-center">
        <Loader2 className="h-5 w-5 animate-spin text-text-tertiary" />
        <p className="text-xs text-text-tertiary">Generating transcript…</p>
      </div>
    )
  }

  if (!transcript) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-text-tertiary" />
      </div>
    )
  }

  if (transcript.words.length === 0) {
    return <EmptyState text="Transcript came back empty." />
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 text-[13px] leading-relaxed text-text-secondary">
      {transcript.words.map((w, i) => (
        <span
          key={i}
          onClick={() => seekTo(w.start, false)}
          className={cn(
            'cursor-pointer rounded px-0.5 transition-colors hover:bg-accent/15 hover:text-text-primary',
          )}
        >
          {w.text}{' '}
        </span>
      ))}
    </div>
  )
}
