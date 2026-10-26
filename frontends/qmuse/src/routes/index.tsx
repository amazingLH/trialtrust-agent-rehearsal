import { createFileRoute } from '@tanstack/react-router';
import { useEffect } from 'react';
import page from '../workbench/index.html.txt?raw';
import styles from '../workbench/style.css.txt?raw';

export const Route = createFileRoute('/')({ component: Workbench });
const body = page.split('<body>', 2)[1].split('</body>', 1)[0];

function Workbench() {
  useEffect(() => {
    import('../workbench-entry.js').catch(() => {
      const error = document.getElementById('auth-error');
      if (error) error.textContent = '页面加载未完成，请刷新重试。';
    });
  }, []);
  return <><style>{styles}</style><div dangerouslySetInnerHTML={{ __html: body }} /></>;
}
