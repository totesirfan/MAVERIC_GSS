import { Toaster as Sonner, type ToasterProps } from "sonner"
import { CircleCheckIcon, InfoIcon, TriangleAlertIcon, OctagonXIcon, Loader2Icon } from "lucide-react"

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="dark"
      className="toaster group"
      closeButton
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      toastOptions={{
        classNames: {
          error: '!bg-[#FF3838] !text-[#080808] !border-[#FF3838] font-semibold',
          warning: '!bg-[#E8B83A] !text-[#080808] !border-[#E8B83A] font-semibold',
          success: '!bg-[#3CC98E] !text-[#080808] !border-[#3CC98E]',
          info: '!bg-[#0E0E0E] !text-[#E5E5E5] !border-[#222222]',
        },
      }}
      style={{
        "--normal-bg": "#0E0E0E",
        "--normal-text": "#E5E5E5",
        "--normal-border": "#222222",
        "--border-radius": "0.375rem",
      } as React.CSSProperties}
      {...props}
    />
  )
}

export { Toaster }
