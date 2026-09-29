// 도자기 이모지 세트 — Codex $imagegen으로 같은 그림체(무광 도자기 3D)로 그린 투명 PNG.
import dislike from "./assets/emoji/dislike.png";
import doc from "./assets/emoji/doc.png";
import done from "./assets/emoji/done.png";
import empty from "./assets/emoji/empty.png";
import fail from "./assets/emoji/fail.png";
import image from "./assets/emoji/image.png";
import like from "./assets/emoji/like.png";
import memory from "./assets/emoji/memory.png";
import newChat from "./assets/emoji/new.png";
import selected from "./assets/emoji/selected.png";
import sermon from "./assets/emoji/sermon.png";
import trash from "./assets/emoji/trash.png";
import upload from "./assets/emoji/upload.png";
import warn from "./assets/emoji/warn.png";

const SRC = {
  dislike, doc, done, empty, fail, image, like, memory, new: newChat, selected, sermon,
  trash, upload, warn,
} as const;

export type EmojiName = keyof typeof SRC;

/** label이 있으면 스크린리더에 읽히고, 없으면 장식으로 숨긴다. */
export function Emoji({ name, size = 18, label }: { name: EmojiName; size?: number; label?: string }) {
  return (
    <img className="emoji" src={SRC[name]} width={size} height={size} draggable={false}
         alt={label ?? ""} aria-hidden={label ? undefined : true} />
  );
}
