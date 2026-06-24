import { useEffect, useState } from 'react';

import { type ArchitectureSection, getArchitecture } from '../lib/api';

/**
 * Fetch the in-context architecture notes once on mount (Epic 15).
 *
 * Static content, so one fetch is enough; returns `[]` until it arrives (the pane shows a loading
 * state) and on failure (the notes are reference copy, not load-bearing).
 */
export function useArchitecture(): ArchitectureSection[] {
  const [sections, setSections] = useState<ArchitectureSection[]>([]);

  useEffect(() => {
    let isCancelled = false;
    getArchitecture()
      .then((response) => {
        if (!isCancelled) setSections(response.sections);
      })
      .catch(() => undefined);
    return () => {
      isCancelled = true;
    };
  }, []);

  return sections;
}
