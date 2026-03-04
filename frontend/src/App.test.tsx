import React from 'react';
import { render, screen } from '@testing-library/react';
import App from './App';

test('renders app title', () => {
  render(<App />);
  const titleElement = screen.getByText(/致同AI审计助手/i);
  expect(titleElement).toBeInTheDocument();
});
