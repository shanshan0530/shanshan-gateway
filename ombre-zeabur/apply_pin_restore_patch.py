from __future__ import annotations

from pathlib import Path


TARGET = Path("/app/ombre/bucket_manager.py")
MARKER = "# --- Reversible pin state / 可逆钉选状态 ---"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    if MARKER in source:
        print("Reversible pin patch already applied.")
        return

    load_block = '''        try:\n            post = frontmatter.load(file_path)\n        except Exception as e:\n            logger.warning(f"Failed to load bucket for update / 加载桶失败: {file_path}: {e}")\n            return False\n\n'''
    load_replacement = load_block + '''        # --- Reversible pin state / 可逆钉选状态 ---\n        # Capture the state before applying kwargs so pinning can be undone exactly.\n        original_pinned = bool(post.get("pinned", False))\n        original_type = str(post.get("type") or "dynamic")\n        try:\n            original_importance = max(1, min(10, int(post.get("importance", 5))))\n        except (TypeError, ValueError):\n            original_importance = 5\n\n'''
    source = replace_once(source, load_block, load_replacement, "capture original pin state")

    pin_block = '''        if "pinned" in kwargs:\n            post["pinned"] = bool(kwargs["pinned"])\n            if kwargs["pinned"]:\n                post["importance"] = 10  # pinned → lock importance to 10\n'''
    pin_replacement = '''        if "pinned" in kwargs:\n            requested_pinned = bool(kwargs["pinned"])\n            post["pinned"] = requested_pinned\n            if requested_pinned:\n                # Save the pre-pin state only on the false → true transition.\n                if not original_pinned:\n                    post["pre_pin_type"] = original_type\n                    post["pre_pin_importance"] = original_importance\n                post["type"] = "permanent"\n                post["importance"] = 10  # pinned → lock importance to 10\n            elif original_pinned and not post.get("protected", False):\n                # Restore the exact state saved when pinning. Legacy pinned buckets\n                # without restoration metadata fall back conservatively to dynamic/5.\n                restored_type = str(post.metadata.pop("pre_pin_type", "") or "dynamic")\n                if restored_type not in {"dynamic", "permanent", "archived", "feel"}:\n                    restored_type = "dynamic"\n                restored_importance = post.metadata.pop("pre_pin_importance", 5)\n                try:\n                    restored_importance = max(1, min(10, int(restored_importance)))\n                except (TypeError, ValueError):\n                    restored_importance = 5\n                post["type"] = restored_type\n                post["importance"] = restored_importance\n'''
    source = replace_once(source, pin_block, pin_replacement, "replace pin transition logic")

    move_block = '''        # --- Auto-move: pinned → permanent/ ---\n        # --- 自动移动：钉选 → permanent/ ---\n        domain = post.get("domain", ["未分类"])\n        if kwargs.get("pinned") and post.get("type") != "permanent":\n            post["type"] = "permanent"\n            with open(file_path, "w", encoding="utf-8") as f:\n                f.write(frontmatter.dumps(post))\n            self._move_bucket(file_path, self.permanent_dir, domain)\n        elif "domain" in kwargs and post.get("type") != "feel":\n            bucket_type = str(post.get("type") or "dynamic")\n            if bucket_type == "archived":\n                target_dir = self.archive_dir\n            elif bucket_type == "permanent":\n                target_dir = self.permanent_dir\n            else:\n                target_dir = self.dynamic_dir\n            self._move_bucket(file_path, target_dir, domain)\n'''
    move_replacement = '''        # --- Auto-move after pin/domain changes / 钉选或主域变化后自动移动 ---\n        domain = post.get("domain", ["未分类"])\n        pin_changed = "pinned" in kwargs and bool(kwargs["pinned"]) != original_pinned\n        if pin_changed or "domain" in kwargs:\n            bucket_type = str(post.get("type") or "dynamic")\n            move_domain = domain\n            if bucket_type == "archived":\n                target_dir = self.archive_dir\n            elif bucket_type == "permanent":\n                target_dir = self.permanent_dir\n            elif bucket_type == "feel":\n                target_dir = self.feel_dir\n                move_domain = ["沉淀物"]\n            else:\n                target_dir = self.dynamic_dir\n            self._move_bucket(file_path, target_dir, move_domain)\n'''
    source = replace_once(source, move_block, move_replacement, "replace pin directory move logic")

    compile(source, str(TARGET), "exec")
    TARGET.write_text(source, encoding="utf-8")
    print("Applied reversible pin/unpin patch to", TARGET)


if __name__ == "__main__":
    main()
