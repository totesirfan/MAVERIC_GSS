import { toast } from 'sonner'

export type ToastVariant = 'error' | 'success' | 'info' | 'warning'
export type ToastSide = 'tx' | 'rx'

// eslint-disable-next-line react-refresh/only-export-components
export function showToast(message: string, variant: ToastVariant = 'info', _side: ToastSide = 'tx') {
  const opts = { duration: variant === 'error' || variant === 'warning' ? 8000 : 3000 }
  switch (variant) {
    case 'error': toast.error(message, opts); break
    case 'success': toast.success(message, opts); break
    case 'warning': toast.warning(message, opts); break
    default: toast.info(message, opts); break
  }
}
