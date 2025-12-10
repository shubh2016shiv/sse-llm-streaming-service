/**
 * LLM Provider Models Configuration
 * 
 * This file contains the mapping of providers to their available models.
 * You can easily modify this file to add/remove models without knowing JavaScript.
 * 
 * Format:
 * - Each provider has a key (e.g., "openai", "anthropic")
 * - Each provider has an array of model objects
 * - Each model object has:
 *   - "value": The model identifier used by the API
 *   - "label": The display name shown in the dropdown
 */

export const PROVIDER_MODELS = {
  openai: [
    { value: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
    { value: "gpt-4", label: "GPT-4" },
    { value: "gpt-4-turbo", label: "GPT-4 Turbo" },
    { value: "gpt-4o", label: "GPT-4o" },
    { value: "gpt-4o-mini", label: "GPT-4o Mini" },
  ],
  anthropic: [
    { value: "claude-3-5-sonnet-20241022", label: "Claude 3.5 Sonnet" },
    { value: "claude-3-opus-20240229", label: "Claude 3 Opus" },
    { value: "claude-3-sonnet-20240229", label: "Claude 3 Sonnet" },
    { value: "claude-3-haiku-20240307", label: "Claude 3 Haiku" },
  ],
  fake: [
    { value: "gpt-3.5-turbo", label: "Fake GPT-3.5 Turbo (Testing)" },
  ],
};

/**
 * Get available models for a provider
 * @param {string} provider - The provider name (e.g., "openai", "anthropic", "fake")
 * @returns {Array} Array of model objects
 */
export const getModelsForProvider = (provider) => {
  return PROVIDER_MODELS[provider] || [];
};

/**
 * Get default model for a provider
 * @param {string} provider - The provider name
 * @returns {string} Default model value
 */
export const getDefaultModelForProvider = (provider) => {
  const models = getModelsForProvider(provider);
  return models.length > 0 ? models[0].value : "";
};

