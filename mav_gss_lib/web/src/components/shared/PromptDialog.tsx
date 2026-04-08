import { useState, useEffect, useRef } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

interface PromptDialogProps {
  open: boolean
  title: string
  placeholder?: string
  required?: boolean
  onSubmit: (value: string) => void
  onCancel: () => void
}

export function PromptDialog({ open, title, placeholder, required, onSubmit, onCancel }: PromptDialogProps) {
  const [value, setValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (open) {
      setValue('')
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])
  /* eslint-enable react-hooks/set-state-in-effect */

  function handleSubmit() {
    if (required && !value.trim()) return
    onSubmit(value)
    setValue('')
  }

  return (
    <Dialog open={open} onOpenChange={v => { if (!v) onCancel() }}>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form onSubmit={e => { e.preventDefault(); handleSubmit() }}>
          <Input
            ref={inputRef}
            value={value}
            onChange={e => setValue(e.target.value)}
            placeholder={placeholder}
            className="text-sm"
          />
          <DialogFooter className="mt-3">
            <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={required && !value.trim()}>
              OK
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
