"use client";

import { ReactNode } from "react";
import { Dialog } from "@/src/components/ui/dialog";

type FormModalProps = {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
  headerActions?: ReactNode;
  dismissDisabled?: boolean;
};

/**
 * Оборачивает форму кабинета в общий модальный слой и передаёт запрет закрытия
 * на время записи, сохраняя кнопки действий и черновик под управлением формы.
 * Назначение функции: Показывает форму в общем модальном слое с управляемым запретом закрытия.
 * Зачем используется: Сохраняет незавершённый ввод при записи и оставляет форму владельцем её действий.
 */
export function FormModal({
  open,
  title,
  description,
  onClose,
  children,
  className,
  headerActions,
  dismissDisabled = false,
}: FormModalProps) {
  return (
    <Dialog
      open={open}
      headerActions={headerActions}
      title={title}
      description={description}
      onClose={onClose}
      dismissDisabled={dismissDisabled}
      className={className}
      contentClassName="p-6"
    >
      {children}
    </Dialog>
  );
}
