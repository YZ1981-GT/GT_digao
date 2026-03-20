/**
 * 应用状态管理Hook
 */
import { useState, useCallback } from 'react';
import { AppState, ConfigData, OutlineData } from '../types';
import { draftStorage } from '../utils/draftStorage';

const initialState: AppState = {
  currentStep: 0,
  config: {
    api_key: '',
    base_url: '',
    model_name: 'abab6.5s-chat',
  },
  fileContent: '',
  projectOverview: '',
  techRequirements: '',
  outlineData: null,
  selectedChapter: '',
};

export const useAppState = () => {
  const [state, setState] = useState<AppState>(() => {
    const draft = draftStorage.loadDraft();
    return {
      ...initialState,
      ...(draft || {}),
    };
  });

  /** 通用字段更新：更新 state 并持久化到 draft */
  const updateFields = useCallback((patch: Partial<AppState>) => {
    setState(prev => ({ ...prev, ...patch }));
    draftStorage.saveDraft(patch);
  }, []);

  // ─── 对外 API 保持不变 ───

  const updateConfig = useCallback((config: ConfigData) => {
    setState(prev => ({ ...prev, config }));
  }, []);

  const updateStep = useCallback((step: number) => {
    updateFields({ currentStep: step });
  }, [updateFields]);

  const updateFileContent = useCallback((fileContent: string) => {
    updateFields({ fileContent });
  }, [updateFields]);

  const updateAnalysisResults = useCallback((overview: string, requirements: string) => {
    updateFields({ projectOverview: overview, techRequirements: requirements });
  }, [updateFields]);

  const updateOutline = useCallback((outlineData: OutlineData) => {
    updateFields({ outlineData });
  }, [updateFields]);

  const updateSelectedChapter = useCallback((chapterId: string) => {
    updateFields({ selectedChapter: chapterId });
  }, [updateFields]);

  const nextStep = useCallback(() => {
    setState(prev => {
      const nextStepValue = Math.min(prev.currentStep + 1, 2);
      draftStorage.saveDraft({ currentStep: nextStepValue });
      return { ...prev, currentStep: nextStepValue };
    });
  }, []);

  const prevStep = useCallback(() => {
    setState(prev => {
      const prevStepValue = Math.max(prev.currentStep - 1, 0);
      draftStorage.saveDraft({ currentStep: prevStepValue });
      return { ...prev, currentStep: prevStepValue };
    });
  }, []);

  return {
    state,
    updateConfig,
    updateStep,
    updateFileContent,
    updateAnalysisResults,
    updateOutline,
    updateSelectedChapter,
    nextStep,
    prevStep,
  };
};
