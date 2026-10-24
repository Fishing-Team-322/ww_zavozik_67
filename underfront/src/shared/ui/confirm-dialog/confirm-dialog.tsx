"use client";

import { ReactNode } from "react";
import { Dialog } from "../dialog";
import { Button } from "../button";

interface ConfirmDialogProps {
  open: boolean;
  title?: string;
  description?: string;
  confirmText?: string;
  cancelText?: string;
  loading?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}

/**
 * Назначение функции: Отображает компонент `ConfirmDialog` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function ConfirmDialog({
  open,
  title = "Подтвердите действие",
  description,
  confirmText = "Подтвердить",
  cancelText = "Отмена",
  loading,
  confirmDisabled,
  onConfirm,
  onCancel,
  children,
}: ConfirmDialogProps) {
  return (
    <Dialog
      open={open}
      title={title}
      description={description}
      onClose={onCancel}
    >
      {children}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel} disabled={loading}>
          {cancelText}
        </Button>
        <Button
          variant="danger"
          onClick={onConfirm}
          loading={loading}
          disabled={confirmDisabled}
        >
          {confirmText}
        </Button>
      </div>
    </Dialog>
  );
}
