'use client'

import { createContext, useContext } from 'react'

/** The workspace being viewed. Components that build workspace URLs read it from here. */
export const WorkspaceIdContext = createContext<string>('')

export const useWorkspaceId = () => useContext(WorkspaceIdContext)
