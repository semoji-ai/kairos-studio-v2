// 선 아이콘 — currentColor를 따르므로 테마 색을 그대로 입는다.
type IconProps = { size?: number };

function Svg({ size = 16, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"
         aria-hidden="true">
      {children}
    </svg>
  );
}

export function PlusIcon(p: IconProps) {
  return <Svg {...p}><path d="M12 5v14M5 12h14" /></Svg>;
}

export function TrashIcon(p: IconProps) {
  return <Svg {...p}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" /></Svg>;
}

export function ThumbUpIcon(p: IconProps) {
  return <Svg {...p}><path d="M7 10v11H4V10h3zm0 0 4-7a2 2 0 0 1 3 2l-1 4h5.5a2 2 0 0 1 2 2.4l-1.4 7A2 2 0 0 1 17.1 21H7" /></Svg>;
}

export function ThumbDownIcon(p: IconProps) {
  return <Svg {...p}><path d="M17 14V3h3v11h-3zm0 0-4 7a2 2 0 0 1-3-2l1-4H5.5a2 2 0 0 1-2-2.4l1.4-7A2 2 0 0 1 6.9 3H17" /></Svg>;
}

export function MemoryIcon(p: IconProps) {
  return <Svg {...p}><path d="M12 8v4l3 2" /><circle cx="12" cy="12" r="9" /></Svg>;
}

export function BookIcon(p: IconProps) {
  return <Svg {...p}><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5zM4 19a2 2 0 0 1 2-2h13" /></Svg>;
}
