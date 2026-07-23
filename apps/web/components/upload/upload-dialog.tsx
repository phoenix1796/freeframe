'use client'

import * as React from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { UploadZone } from './upload-zone'

interface UploadDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  pendingFiles: File[]
  onFilesSelected: (files: File[]) => void
  onChangeFiles: () => void
  onStartUpload: () => void
  /** Only shown for single-file selections — new-version uploads pass this
   * as undefined since the asset's name is already fixed. */
  assetName?: string
  onAssetNameChange?: (name: string) => void
}

/** Shared upload confirmation dialog — same file list and start/change
 * actions whether you're uploading a brand new asset or a new version of
 * an existing one. */
export function UploadDialog({
  open,
  onOpenChange,
  title,
  description,
  pendingFiles,
  onFilesSelected,
  onChangeFiles,
  onStartUpload,
  assetName,
  onAssetNameChange,
}: UploadDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-bg-secondary p-6 shadow-xl data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95">
          <Dialog.Close className="absolute right-4 top-4 text-text-tertiary hover:text-text-primary transition-colors">
            <X className="h-4 w-4" />
          </Dialog.Close>
          <Dialog.Title className="text-base font-semibold text-text-primary">
            {title}
          </Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            {description}
          </Dialog.Description>
          <div className="mt-4 space-y-4">
            {pendingFiles.length === 0 ? (
              <UploadZone onFilesSelected={onFilesSelected} />
            ) : (
              <>
                <div className="rounded-lg border border-border bg-bg-tertiary">
                  <div className="px-3 py-2 text-xs font-medium text-text-tertiary border-b border-border">
                    {pendingFiles.length} file{pendingFiles.length !== 1 ? 's' : ''} selected
                  </div>
                  <div className="max-h-40 overflow-y-auto divide-y divide-border">
                    {pendingFiles.map((f, i) => (
                      <div key={i} className="flex items-center justify-between px-3 py-1.5">
                        <span className="text-sm text-text-primary truncate mr-2">{f.name}</span>
                        <span className="text-xs text-text-tertiary shrink-0">
                          {f.size < 1024 * 1024
                            ? `${(f.size / 1024).toFixed(0)} KB`
                            : `${(f.size / (1024 * 1024)).toFixed(1)} MB`}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                {onAssetNameChange && pendingFiles.length === 1 && (
                  <Input
                    label="Asset name"
                    value={assetName ?? ''}
                    onChange={(e) => onAssetNameChange(e.target.value)}
                    placeholder="e.g. Hero Video Final"
                  />
                )}
                <div className="flex justify-end gap-2">
                  <Button type="button" variant="secondary" size="sm" onClick={onChangeFiles}>
                    Change files
                  </Button>
                  <Button size="sm" onClick={onStartUpload}>
                    Start upload
                  </Button>
                </div>
              </>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
