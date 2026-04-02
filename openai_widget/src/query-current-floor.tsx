import React from 'react';
import { createRoot } from 'react-dom/client';
import { getQueryCurrentFloorData } from './runtime';
import './styles.css';

const data = getQueryCurrentFloorData();
const answer = data.answer?.trim() || "Here's what I found.";
const related = Array.isArray(data.relatedFloors) ? data.relatedFloors.slice(0, 6) : [];

function App() {
  return (
    <section className="card">
      <div className="answer">{answer}</div>
      {related.length ? (
        <div className="links">
          {related.map((item, index) => {
            const floorId = (item.floor_id || '').trim();
            const label = (item.label || item.floorName || floorId || '').trim();
            if (!floorId) return null;
            return (
              <a key={index} className="link" href={`https://${floorId}.xfloor.ai`} target="_blank" rel="noreferrer">
                {label.startsWith('@') ? label : `@${label}`}
              </a>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
