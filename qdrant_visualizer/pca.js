/**
 * client-side PCA (Principal Component Analysis)
 * Projects high-dimensional vectors (e.g., 1024-D) to 3D for visualization.
 */

export class PCA {
    /**
     * Projects an array of vectors to 3D space.
     * @param {number[][]} data - Array of N vectors, each of dimension D.
     * @returns {number[][]} - Array of N 3D vectors.
     */
    static project(data, targetDimension = 3) {
        if (!data || data.length === 0) return [];
        const n = data.length;
        const d = data[0].length;

        // If dataset is extremely small or 3D/smaller, pad or return as-is
        if (d <= targetDimension) {
            return data.map(v => {
                const coords = [0, 0, 0];
                for (let i = 0; i < Math.min(d, 3); i++) coords[i] = v[i];
                return coords;
            });
        }

        // 1. Mean-centering
        const means = new Float32Array(d);
        for (let j = 0; j < d; j++) {
            let sum = 0;
            for (let i = 0; i < n; i++) {
                sum += data[i][j];
            }
            means[j] = sum / n;
        }

        const X = data.map(v => {
            const centered = new Float32Array(d);
            for (let j = 0; j < d; j++) {
                centered[j] = v[j] - means[j];
            }
            return centered;
        });

        // 2. Compute Covariance Matrix (size D x D)
        // Since D can be 1024, D x D is 1,048,576 elements.
        // We optimize storage by using a flat Float32Array.
        const cov = new Float32Array(d * d);
        const divisor = n > 1 ? n - 1 : 1;

        console.time("PCA Covariance Matrix");
        for (let i = 0; i < d; i++) {
            for (let j = i; j < d; j++) {
                let sum = 0;
                for (let k = 0; k < n; k++) {
                    sum += X[k][i] * X[k][j];
                }
                const val = sum / divisor;
                cov[i * d + j] = val;
                cov[j * d + i] = val; // symmetric
            }
        }
        console.timeEnd("PCA Covariance Matrix");

        // 3. Power Iteration with Hotelling Deflation to extract eigenvectors
        console.time("PCA Eigenvectors");
        const eigenvectors = [];
        for (let step = 0; step < targetDimension; step++) {
            // Start with a random non-zero vector
            let b = new Float32Array(d);
            for (let i = 0; i < d; i++) b[i] = Math.random() - 0.5;
            
            // Normalize
            let norm = 0;
            for (let i = 0; i < d; i++) norm += b[i] * b[i];
            norm = Math.sqrt(norm);
            if (norm > 0) {
                for (let i = 0; i < d; i++) b[i] /= norm;
            }

            // Power iteration
            const maxIterations = 35;
            for (let iter = 0; iter < maxIterations; iter++) {
                const nextB = new Float32Array(d);
                for (let i = 0; i < d; i++) {
                    let sum = 0;
                    for (let j = 0; j < d; j++) {
                        sum += cov[i * d + j] * b[j];
                    }
                    nextB[i] = sum;
                }

                // Normalize nextB
                let nextNorm = 0;
                for (let i = 0; i < d; i++) nextNorm += nextB[i] * nextB[i];
                nextNorm = Math.sqrt(nextNorm);
                
                if (nextNorm === 0) break;
                for (let i = 0; i < d; i++) b[i] = nextB[i] / nextNorm;
            }

            // b is now the eigenvector. Compute eigenvalue: lambda = b^T * Cov * b
            // since Cov * b = lambda * b, we can just project Cov * b onto b
            const covB = new Float32Array(d);
            for (let i = 0; i < d; i++) {
                let sum = 0;
                for (let j = 0; j < d; j++) {
                    sum += cov[i * d + j] * b[j];
                }
                covB[i] = sum;
            }
            let eigenvalue = 0;
            for (let i = 0; i < d; i++) eigenvalue += b[i] * covB[i];

            eigenvectors.push({ vector: b, eigenvalue: eigenvalue });

            // Hotelling Deflation: Cov = Cov - eigenvalue * b * b^T
            for (let i = 0; i < d; i++) {
                for (let j = 0; j < d; j++) {
                    cov[i * d + j] -= eigenvalue * b[i] * b[j];
                }
            }
        }
        console.timeEnd("PCA Eigenvectors");

        // 4. Project original data onto the top principal components
        console.time("PCA Projection");
        const projected = [];
        for (let i = 0; i < n; i++) {
            const pt = X[i];
            const coord = [0, 0, 0];
            for (let dim = 0; dim < targetDimension; dim++) {
                const ev = eigenvectors[dim].vector;
                let val = 0;
                for (let j = 0; j < d; j++) {
                    val += pt[j] * ev[j];
                }
                coord[dim] = val;
            }
            projected.push(coord);
        }
        console.timeEnd("PCA Projection");

        return {
            points: projected,
            eigenvalues: eigenvectors.map(e => e.eigenvalue)
        };
    }
}
