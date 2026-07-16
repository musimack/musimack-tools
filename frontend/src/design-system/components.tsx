import type {
  ButtonHTMLAttributes,
  DialogHTMLAttributes,
  HTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  TableHTMLAttributes,
} from 'react';
import { useEffect, useId, useRef } from 'react';

export const FRONTEND_DESIGN_SYSTEM_VERSION = 'seo-toolkit-frontend-design-system-v1' as const;

export function Button({ className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`button ${className}`.trim()} {...props} />;
}

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input type="text" {...props} />;
}

export function PasswordInput(props: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'>) {
  return <input type="password" {...props} />;
}

export function FormField({
  id,
  label,
  error,
  children,
}: {
  id: string;
  label: string;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <div className="form-field">
      <label htmlFor={id}>{label}</label>
      {children}
      {error ? <ValidationMessage id={`${id}-error`}>{error}</ValidationMessage> : null}
    </div>
  );
}

export function ValidationMessage({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <p id={id} className="form-error" role="alert">
      {children}
    </p>
  );
}

export function Alert({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'warning' | 'error';
  children: ReactNode;
}) {
  return (
    <div className={`alert alert--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  );
}

export function Card({ className = '', ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={`card ${className}`.trim()} {...props} />;
}

export function PageHeader({
  eyebrow,
  title,
  children,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-header">
      {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
      <h1>{title}</h1>
      {children ? <p className="page-intro">{children}</p> : null}
    </header>
  );
}

export function StatusBadge({
  tone,
  children,
}: {
  tone: 'positive' | 'neutral' | 'warning';
  children: ReactNode;
}) {
  return <span className={`status status--${tone}`}>{children}</span>;
}

export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card className="empty-state">
      <div className="empty-state__mark" aria-hidden="true">
        ◇
      </div>
      <h2>{title}</h2>
      <p>{children}</p>
    </Card>
  );
}

export function ErrorState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card className="error-state">
      <span aria-hidden="true">!</span>
      <h2>{title}</h2>
      <p>{children}</p>
    </Card>
  );
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <span className="spinner" role="status">
      <span className="loader" aria-hidden="true" />
      <VisuallyHidden>{label}</VisuallyHidden>
    </span>
  );
}

export function Skeleton({ label = 'Loading content' }: { label?: string }) {
  return <span className="skeleton" role="status" aria-label={label} />;
}

export function DialogFoundation({
  title,
  children,
  open,
  onClose,
  ...props
}: Omit<DialogHTMLAttributes<HTMLDialogElement>, 'open' | 'onClose'> & {
  title: string;
  children: ReactNode;
  open: boolean;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);
  return (
    <dialog
      ref={dialog}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      {...props}
    >
      <h2 id={titleId}>{title}</h2>
      {children}
      <Button type="button" autoFocus onClick={onClose}>
        Close
      </Button>
    </dialog>
  );
}

export function TableFoundation(props: TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="table-scroll" tabIndex={0}>
      <table {...props} />
    </div>
  );
}

export function NavigationItem({
  active = false,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { active?: boolean }) {
  return <span aria-current={active ? 'page' : undefined} {...props} />;
}

export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="visually-hidden">{children}</span>;
}

export function SkipLink({ target = 'main-content' }: { target?: string }) {
  return (
    <a className="skip-link" href={`#${target}`}>
      Skip to content
    </a>
  );
}

export function LoadingScreen() {
  return (
    <main className="centered-page" aria-busy="true">
      <Spinner label="Verifying the current session" />
      <h1>Opening your workspace</h1>
      <p>Verifying the current session…</p>
    </main>
  );
}
