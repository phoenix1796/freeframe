'use client'

import React, { useCallback, useState } from 'react'
import { Folder, MoreHorizontal, Pencil, Trash, Share2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { NameDialog } from './name-dialog'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import type { Folder as FolderType } from '@/types'

interface FolderCardProps {
  folder: FolderType
  selected?: boolean
  onOpen: (folder: FolderType) => void
  onRename?: (folderId: string, name: string) => Promise<void>
  onDelete?: (folderId: string) => Promise<void>
  onShare?: (folderId: string, folderName: string) => Promise<void>
  onDropItems?: (targetFolderId: string, assetIds: string[], folderIds: string[]) => void
  className?: string
}

export function FolderCard({
  folder,
  selected,
  onOpen,
  onRename,
  onDelete,
  onShare,
  onDropItems,
  className,
}: FolderCardProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)
  const [renameOpen, setRenameOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const menuRef = React.useRef<HTMLDivElement>(null)

  // Close menu on outside click
  React.useEffect(() => {
    if (!menuOpen) return
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [menuOpen])

  // Draggable
  const handleDragStart = useCallback(
    (e: React.DragEvent) => {
      e.dataTransfer.setData(
        'application/json',
        JSON.stringify({ folderIds: [folder.id], assetIds: [] }),
      )
      e.dataTransfer.effectAllowed = 'move'
    },
    [folder.id],
  )

  // Drop target
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setIsDragOver(true)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragOver(false)
      try {
        const data = JSON.parse(e.dataTransfer.getData('application/json'))
        // Don't allow dropping a folder onto itself
        if (data.folderIds?.includes(folder.id)) return
        onDropItems?.(folder.id, data.assetIds ?? [], data.folderIds ?? [])
      } catch {}
    },
    [folder.id, onDropItems],
  )

  return (
    <>
      <div
        className={cn(
          'group relative flex flex-col items-center rounded-lg p-3 cursor-pointer transition-colors hover:bg-bg-hover',
          selected && 'bg-accent/10',
          isDragOver && 'bg-accent/10 ring-2 ring-accent/50',
          menuOpen && 'z-[60]',
          className,
        )}
        draggable
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        onDoubleClick={() => onOpen(folder)}
        onClick={() => onOpen(folder)}
      >
        {/* Folder icon — Finder-style: the icon alone signals "folder", no
            content preview, so it never gets confused with an asset card. */}
        <Folder
          className="h-16 w-16 text-accent shrink-0"
          fill="currentColor"
          fillOpacity={0.18}
          strokeWidth={1.5}
        />

        {/* Name + item count — outside/below the icon, not inside a card */}
        <div className="mt-1 flex flex-col items-center gap-0.5 max-w-full">
          <p className="text-sm font-medium text-text-primary text-center line-clamp-2 break-words max-w-full px-1">
            {folder.name}
          </p>
          <p className="text-xs text-text-tertiary">
            {folder.item_count} {folder.item_count === 1 ? 'item' : 'items'}
          </p>
        </div>

        {/* Menu — top-right, appears on hover (matches the icon-view layout) */}
        <div className="absolute right-1 top-1" ref={menuRef}>
          <button
            className="opacity-0 group-hover:opacity-100 flex items-center justify-center h-6 w-6 rounded hover:bg-bg-hover transition-opacity shrink-0"
            onClick={(e) => {
              e.stopPropagation()
              setMenuOpen((p) => !p)
            }}
          >
            <MoreHorizontal className="h-3.5 w-3.5 text-text-tertiary" />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full mt-1 z-50 w-40 rounded-lg border border-border bg-bg-elevated shadow-xl py-1">
              <button
                className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover"
                onClick={(e) => {
                  e.stopPropagation()
                  setMenuOpen(false)
                  setRenameOpen(true)
                }}
              >
                <Pencil className="h-3 w-3" /> Rename
              </button>
              <button
                className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover"
                onClick={(e) => {
                  e.stopPropagation()
                  setMenuOpen(false)
                  onShare?.(folder.id, folder.name)
                }}
              >
                <Share2 className="h-3 w-3" /> Share
              </button>
              <button
                className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/10"
                onClick={(e) => {
                  e.stopPropagation()
                  setMenuOpen(false)
                  setDeleteOpen(true)
                }}
              >
                <Trash className="h-3 w-3" /> Delete
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Rename dialog */}
      <NameDialog
        open={renameOpen}
        onOpenChange={setRenameOpen}
        title="Rename Folder"
        placeholder="Folder name"
        defaultValue={folder.name}
        submitLabel="Rename"
        onSubmit={(name) => onRename?.(folder.id, name)}
      />

      {/* Delete confirmation */}
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={`Delete "${folder.name}"?`}
        description="This folder and all its contents will be moved to trash. You can restore them later."
        confirmLabel="Delete"
        variant="danger"
        onConfirm={() => onDelete?.(folder.id)}
      />
    </>
  )
}
